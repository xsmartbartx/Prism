"""Dataset catalog, versions, querying, recommendation and export."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from data.query import QuerySpec
from presentation.export import to_csv, to_xlsx
from presentation.recommend import FieldInfo, recommend
from server.api.deps import actor, services
from server.api.routes.imports import read_upload
from server.api.serializers import dataset_out, version_out
from server.container import Services
from server.errors import BadRequest
from server.services import audit
from server.services.context import Actor
from server.services.queries import jsonable_rows

router = APIRouter(prefix="/api/v1/datasets", tags=["datasets"])


class DatasetPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    tags: list[str] | None = None
    status: str | None = None


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
