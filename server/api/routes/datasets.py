"""Dataset catalog, versions, querying, recommendation and export."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from data.query import QuerySpec
from presentation.export import to_csv, to_xlsx
from presentation.recommend import FieldInfo, recommend
from server.api.deps import actor, services
from server.api.routes.imports import read_upload
from server.api.serializers import dataset_out, link_out, version_out
from server.container import Services
from server.errors import BadRequest
from server.services import audit, links
from server.services.context import Actor
from server.services.queries import jsonable_rows

router = APIRouter(prefix="/api/v1/datasets", tags=["datasets"])


class DatasetPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    tags: list[str] | None = None
    status: str | None = None


class CalcIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    expression: str = Field(min_length=1, max_length=1000)


class CalculationsIn(BaseModel):
    calculations: list[CalcIn] = Field(default_factory=list, max_length=25)


class CalcPreviewIn(BaseModel):
    expression: str = Field(min_length=1, max_length=1000)
    # The fields defined so far (unsaved edits included), which the formula may use.
    calculations: list[CalcIn] = Field(default_factory=list, max_length=25)


def _chart_columns(query: dict[str, Any]) -> set[str]:
    cols = set(query.get("dimensions") or []) | set(query.get("columns") or [])
    cols |= {m.get("column") for m in query.get("measures") or []}
    cols |= {f.get("column") for f in query.get("filters") or []}
    cols |= {s.get("column") for s in query.get("sort") or []}
    return {c for c in cols if isinstance(c, str)}


class LinkIn(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    schedule: str = "manual"


class RecommendIn(BaseModel):
    fields: list[str] = Field(min_length=1, max_length=6)
    title: str | None = None


def _filename(name: str, ext: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in name).strip() or "export"
    return f"{safe[:80]}.{ext}"


@router.get("")
def list_datasets(
    q: str = Query(default="", max_length=200),
    a: Actor = Depends(actor),
    svc: Services = Depends(services),
) -> list[dict[str, Any]]:
    from server.db.models import DatasetVersion

    with svc.db.transaction() as s:
        out = []
        for ds in svc.artifacts.list_datasets(s, a, q):
            v = s.get(DatasetVersion, ds.current_version_id) if ds.current_version_id else None
            d = dataset_out(ds)
            if v:
                d.update(
                    row_count=v.row_count,
                    column_count=len(v.columns),
                    quarantine_count=v.quarantine_count,
                    version=v.version,
                )
            out.append(d)
        return out


@router.post("/sample", status_code=201)
def load_sample(a: Actor = Depends(actor), svc: Services = Depends(services)) -> dict[str, Any]:
    """Create a ready-to-explore sample sales dataset (onboarding and demos)."""
    from pathlib import Path

    from server.schemas import ColumnDecision, CommitImport
    from server.services.licensing import require_feature

    a.require("author")
    raw = (Path(__file__).resolve().parents[2] / "samples" / "sample-sales.csv").read_bytes()
    with svc.db.transaction() as s:
        require_feature(svc, s, "datasets")
        imp = svc.imports.create(s, a, "sample-sales.csv", raw)
        p = imp.proposal
        req = CommitImport(
            dataset_name="Sample sales",
            description="Demo orders 2025–2026 by region, channel and product. Safe to delete.",
            header_row=p["header_row"],
            data_start_row=p["data_start_row"],
            locale=p["locale"],
            tags=["sample"],
            columns=[
                ColumnDecision(
                    index=c["index"],
                    source_name=c["source_name"],
                    name=c["name"],
                    type=c["type"],
                    role=c["role"],
                    locale=c["locale"],
                )
                for c in p["columns"]
            ],
        )
        loaded = svc.imports.commit(s, a, imp, req)
        return dataset_out(loaded.dataset, loaded.version)


@router.get("/{dataset_id}")
def get_dataset(
    dataset_id: str, a: Actor = Depends(actor), svc: Services = Depends(services)
) -> dict[str, Any]:
    with svc.db.transaction() as s:
        ds = svc.artifacts.get_dataset(s, a, dataset_id)
        version = svc.queries.current_version(s, ds) if ds.current_version_id else None
        out = dataset_out(ds, version)
        out["versions"] = [
            {k: v for k, v in version_out(x).items() if k not in ("profile", "columns")}
            for x in svc.artifacts.versions(s, ds)
        ]
        return out


@router.patch("/{dataset_id}")
def patch_dataset(
    dataset_id: str,
    body: DatasetPatch,
    a: Actor = Depends(actor),
    svc: Services = Depends(services),
) -> dict[str, Any]:
    with svc.db.transaction() as s:
        ds = svc.artifacts.get_dataset(s, a, dataset_id)
        svc.artifacts.update_dataset(s, a, ds, body.model_dump(exclude_unset=True))
        return dataset_out(ds)


@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(
    dataset_id: str, a: Actor = Depends(actor), svc: Services = Depends(services)
) -> None:
    with svc.db.transaction() as s:
        ds = svc.artifacts.get_dataset(s, a, dataset_id)
        svc.artifacts.delete_dataset(s, a, ds)


@router.post("/{dataset_id}/refresh", status_code=201)
async def refresh(
    dataset_id: str,
    file: UploadFile = File(...),
    a: Actor = Depends(actor),
    svc: Services = Depends(services),
) -> dict[str, Any]:
    a.require("author")
    data = await read_upload(file, svc.settings.max_upload_bytes)
    with svc.db.transaction() as s:
        ds = svc.artifacts.get_dataset(s, a, dataset_id)
        loaded = svc.imports.refresh(s, a, ds, file.filename or "refresh", data)
        return {
            **dataset_out(loaded.dataset, loaded.version),
            "load": {
                "rows": loaded.result.row_count,
                "quarantined": loaded.result.quarantine_count,
                "reasons": loaded.result.reasons,
                "drift": loaded.result.drift,
            },
        }


@router.put("/{dataset_id}/calculations")
def put_calculations(
    dataset_id: str,
    body: CalculationsIn,
    a: Actor = Depends(actor),
    svc: Services = Depends(services),
) -> dict[str, Any]:
    """Replace the dataset's calculated fields (each may use the ones before it)."""
    from data.query.calc import build
    from server.db.models import Chart
    from server.errors import Conflict
    from server.services.queries import version_types

    a.require("author")
    with svc.db.transaction() as s:
        ds = svc.artifacts.get_dataset(s, a, dataset_id)
        version = svc.queries.current_version(s, ds)
        calcs = build([c.model_dump() for c in body.calculations], version_types(version))
        removed = {c["name"] for c in ds.calculations or []} - {c.name for c in calcs}
        if removed:
            charts = s.scalars(select(Chart).where(Chart.dataset_id == ds.id)).all()
            users = sorted(c.name for c in charts if _chart_columns(c.query_spec) & removed)
            if users:
                names = ", ".join(f"[{n}]" for n in sorted(removed))
                raise Conflict(
                    f"Charts use {names}: {', '.join(users[:5])}. Change those charts first."
                )
        ds.calculations = [
            {"name": c.name, "expression": c.expression, "type": c.type, "aggregate": c.aggregate}
            for c in calcs
        ]
        audit.record(
            s,
            a,
            "dataset.calculations",
            target_type="dataset",
            target_id=ds.id,
            description=f"{ds.name} has {len(calcs)} calculated field(s)",
            details={"fields": [{"name": c.name, "expression": c.expression} for c in calcs]},
        )
        return {"calculations": ds.calculations}


@router.post("/{dataset_id}/calculations/preview")
def preview_calculation(
    dataset_id: str,
    body: CalcPreviewIn,
    a: Actor = Depends(actor),
    svc: Services = Depends(services),
) -> dict[str, Any]:
    """Check a formula and show what it gives for the first rows."""
    from data.query.calc import Calculation, build, compile_formula
    from data.query.spec import AggFunction, AggregationSpec
    from server.services.queries import version_types

    a.require("author")
    with svc.db.transaction() as s:
        ds = svc.artifacts.get_dataset(s, a, dataset_id)
        version = svc.queries.current_version(s, ds)
        columns = version_types(version)
        base = build([c.model_dump() for c in body.calculations], columns)
        known = columns | {c.name: c.type for c in base if not c.aggregate}
        f = compile_formula(body.expression, known, {c.name: c for c in base if c.aggregate})
        probe = Calculation(
            "__prism_preview",
            body.expression,
            f.type,
            f.sql,
            tuple(f.params),
            frozenset(f.uses),
            f.aggregate,
        )
        if f.aggregate:
            # A measure: show its value over the whole dataset.
            spec = QuerySpec(
                measures=[AggregationSpec(column=probe.name, function=AggFunction.VALUE)]
            )
            outcome = svc.queries.run(s, a, ds, spec, calculations=[*base, probe])
            total = jsonable_rows(outcome.result.rows)
            return {
                "type": f.type,
                "aggregate": True,
                "columns": [],
                "rows": [{"inputs": {}, "value": total[0].get(probe.name) if total else None}],
            }
        shown = [c for c in known if c in f.uses][:4]
        outcome = svc.queries.run(
            s,
            a,
            ds,
            QuerySpec(columns=[*shown, probe.name], limit=8),
            calculations=[*base, probe],
        )
        rows = jsonable_rows(outcome.result.rows)
        return {
            "type": f.type,
            "aggregate": False,
            "columns": shown,
            "rows": [
                {"inputs": {c: r.get(c) for c in shown}, "value": r.get(probe.name)} for r in rows
            ],
        }


@router.get("/{dataset_id}/link")
def get_link(
    dataset_id: str, a: Actor = Depends(actor), svc: Services = Depends(services)
) -> dict[str, Any]:
    with svc.db.transaction() as s:
        ds = svc.artifacts.get_dataset(s, a, dataset_id)
        link = links.get_link(s, a, ds)
        from server.services.licensing import current_state

        return {
            "link": link_out(link) if link else None,
            # Whether the plan allows a schedule, so the UI can say so before anyone picks one.
            "can_schedule": "scheduled_refresh" in current_state(svc, s).plan.features,
        }


@router.put("/{dataset_id}/link")
def put_link(
    dataset_id: str, body: LinkIn, a: Actor = Depends(actor), svc: Services = Depends(services)
) -> dict[str, Any]:
    with svc.db.transaction() as s:
        ds = svc.artifacts.get_dataset(s, a, dataset_id)
        return {"link": link_out(links.set_link(svc, s, a, ds, body.url, body.schedule))}


@router.delete("/{dataset_id}/link", status_code=204)
def delete_link(
    dataset_id: str, a: Actor = Depends(actor), svc: Services = Depends(services)
) -> None:
    with svc.db.transaction() as s:
        links.delete_link(s, a, svc.artifacts.get_dataset(s, a, dataset_id))


@router.post("/{dataset_id}/link/refresh")
def refresh_link(
    dataset_id: str, a: Actor = Depends(actor), svc: Services = Depends(services)
) -> dict[str, Any]:
    """Download the dataset's link now; a changed file becomes a new version."""
    outcome = links.refresh(svc, a, dataset_id)
    with svc.db.transaction() as s:
        ds = svc.artifacts.get_dataset(s, a, dataset_id)
        link = links.get_link(s, a, ds)
        version = svc.queries.current_version(s, ds) if ds.current_version_id else None
        return {
            "outcome": {
                "status": outcome.status,
                "error": outcome.error,
                "version": outcome.version,
                "rows": outcome.rows,
                "quarantined": outcome.quarantined,
            },
            "link": link_out(link) if link else None,
            "dataset": dataset_out(ds, version),
        }


@router.get("/{dataset_id}/versions/{version_id}")
def get_version(
    dataset_id: str, version_id: str, a: Actor = Depends(actor), svc: Services = Depends(services)
) -> dict[str, Any]:
    with svc.db.transaction() as s:
        ds = svc.artifacts.get_dataset(s, a, dataset_id)
        return version_out(svc.queries.current_version(s, ds, version_id))


@router.get("/{dataset_id}/quarantine")
def quarantine(
    dataset_id: str, a: Actor = Depends(actor), svc: Services = Depends(services)
) -> list[dict[str, Any]]:
    with svc.db.transaction() as s:
        ds = svc.artifacts.get_dataset(s, a, dataset_id)
        return svc.artifacts.quarantine_rows(s, a, ds)


@router.get("/{dataset_id}/rows")
def rows(
    dataset_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    a: Actor = Depends(actor),
    svc: Services = Depends(services),
) -> dict[str, Any]:
    with svc.db.transaction() as s:
        ds = svc.artifacts.get_dataset(s, a, dataset_id)
        outcome = svc.queries.run(s, a, ds, QuerySpec(limit=limit, offset=offset))
        return {
            "columns": list(outcome.result.columns),
            "types": outcome.column_types,
            "rows": jsonable_rows(outcome.result.rows),
            "total": outcome.result.row_count,
        }


@router.post("/{dataset_id}/query")
def query(
    dataset_id: str, spec: QuerySpec, a: Actor = Depends(actor), svc: Services = Depends(services)
) -> dict[str, Any]:
    a.require("explore")
    with svc.db.transaction() as s:
        ds = svc.artifacts.get_dataset(s, a, dataset_id)
        outcome = svc.queries.run(s, a, ds, spec)
        return {
            "columns": list(outcome.result.columns),
            "rows": jsonable_rows(outcome.result.rows),
            "total": outcome.result.row_count,
            "truncated": outcome.result.truncated,
            "plan_hash": outcome.result.plan_hash,
            "dataset_version": outcome.version.version,
            "cached": outcome.cached,
        }


@router.post("/{dataset_id}/recommend")
def recommend_chart(
    dataset_id: str, body: RecommendIn, a: Actor = Depends(actor), svc: Services = Depends(services)
) -> dict[str, Any]:
    from datetime import date

    with svc.db.transaction() as s:
        ds = svc.artifacts.get_dataset(s, a, dataset_id)
        version = svc.queries.current_version(s, ds)
        cols = {c["name"]: c for c in version.columns}
        prof = version.profile.get("columns", {})
        fields = []
        for name in body.fields:
            if name not in cols:
                raise BadRequest(f"Unknown column '{name}'")
            p = prof.get(name, {})
            span = None
            if cols[name]["type"] == "date" and p.get("min") and p.get("max"):
                span = (date.fromisoformat(p["max"]) - date.fromisoformat(p["min"])).days
            fields.append(
                FieldInfo(
                    name,
                    cols[name]["type"],
                    cols[name]["role"],
                    distinct=p.get("distinct"),
                    date_span_days=span,
                )
            )
        try:
            rec = recommend(fields, title=body.title)
        except ValueError as exc:
            raise BadRequest(str(exc)) from exc
        return rec.to_dict()


@router.get("/{dataset_id}/export")
def export(
    dataset_id: str,
    format: str = Query(default="csv", pattern="^(csv|xlsx)$"),
    a: Actor = Depends(actor),
    svc: Services = Depends(services),
) -> Response:
    a.require("explore")
    with svc.db.transaction() as s:
        ds = svc.artifacts.get_dataset(s, a, dataset_id)
        outcome = svc.queries.run(
            s,
            a,
            ds,
            QuerySpec(limit=svc.settings.query_row_limit),
            max_limit=svc.settings.query_row_limit,
        )
        audit.record(
            s,
            a,
            "dataset.export",
            target_type="dataset",
            target_id=ds.id,
            description=f"Exported {ds.name} as {format}",
            details={"rows": len(outcome.result.rows), "version": outcome.version.version},
        )
        name = ds.name
    cols, data = list(outcome.result.columns), list(outcome.result.rows)
    if format == "xlsx":
        body = to_xlsx(cols, data, sheet=name)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        body, media = to_csv(cols, data), "text/csv; charset=utf-8"
    return Response(
        content=body,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{_filename(name, format)}"'},
    )
