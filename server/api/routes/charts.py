"""Charts, dashboards and share links."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from presentation.export import to_csv, to_xlsx
from server.api.deps import actor, services
from server.api.routes.datasets import _filename
from server.api.serializers import chart_out, dashboard_out, share_out
from server.container import Services
from server.errors import NotFound
from server.services import audit
from server.services.artifacts import parse_specs
from server.services.context import Actor
from server.services.dashboard_filters import MAX_FILTERS, parse_cross_filter, parse_selections
from server.services.queries import jsonable_rows

router = APIRouter(prefix="/api/v1", tags=["charts"])

SVG = "image/svg+xml"


class ChartIn(BaseModel):
    dataset_id: str
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    query: dict[str, Any]
    view: dict[str, Any]


class PreviewIn(BaseModel):
    dataset_id: str
    query: dict[str, Any]
    view: dict[str, Any]


class Tile(BaseModel):
    chart_id: str
    x: int = 0
    y: int = 0
    w: int = 6
    h: int = 4


class DashboardFilterIn(BaseModel):
    field: str = Field(min_length=1, max_length=200)
    kind: Literal["values", "date_range"] = "values"
    label: str = Field(default="", max_length=80)


class DashboardIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    layout: list[Tile] = Field(default_factory=list)
    # Left out, a dashboard keeps its filters (minus fields no tile has any more).
    filters: list[DashboardFilterIn] | None = Field(default=None, max_length=MAX_FILTERS)


class FilterFieldsIn(BaseModel):
    chart_ids: list[str] = Field(default_factory=list, max_length=48)


def _filters(body: DashboardIn) -> list[dict[str, Any]] | None:
    return None if body.filters is None else [f.model_dump() for f in body.filters]


class ShareIn(BaseModel):
    artifact_type: str = Field(pattern="^(chart|dashboard)$")
    artifact_id: str
    expires_in_hours: int | None = Field(default=None, ge=1, le=24 * 365 * 5)
    allow_embed: bool = False


# ----------------------------------------------------------------------
# Charts
# ----------------------------------------------------------------------


@router.post("/charts/preview")
def preview(
    body: PreviewIn, a: Actor = Depends(actor), svc: Services = Depends(services)
) -> dict[str, Any]:
    a.require("explore")
    with svc.db.transaction() as s:
        ds = svc.artifacts.get_dataset(s, a, body.dataset_id)
        q, v = parse_specs(body.query, body.view)
        r = svc.artifacts.render(s, a, ds, q, v)
        return {
            "svg": r.svg,
            "columns": list(r.outcome.result.columns),
            "rows": jsonable_rows(r.outcome.result.rows[:500]),
            "total": r.outcome.result.row_count,
            "truncated": r.outcome.result.truncated,
        }


@router.get("/charts")
def list_charts(
    dataset_id: str | None = None,
    q: str = Query(default="", max_length=200),
    a: Actor = Depends(actor),
    svc: Services = Depends(services),
) -> list[dict[str, Any]]:
    with svc.db.transaction() as s:
        return [chart_out(c) for c in svc.artifacts.list_charts(s, a, dataset_id=dataset_id, q=q)]


@router.post("/charts", status_code=201)
def create_chart(
    body: ChartIn, a: Actor = Depends(actor), svc: Services = Depends(services)
) -> dict[str, Any]:
    with svc.db.transaction() as s:
        c = svc.artifacts.save_chart(
            s,
            a,
            dataset_id=body.dataset_id,
            name=body.name,
            description=body.description,
            query=body.query,
            view=body.view,
        )
        return chart_out(c)


@router.get("/charts/{chart_id}")
def get_chart(
    chart_id: str, a: Actor = Depends(actor), svc: Services = Depends(services)
) -> dict[str, Any]:
    with svc.db.transaction() as s:
        return chart_out(svc.artifacts.get_chart(s, a, chart_id))


@router.put("/charts/{chart_id}")
def update_chart(
    chart_id: str, body: ChartIn, a: Actor = Depends(actor), svc: Services = Depends(services)
) -> dict[str, Any]:
    with svc.db.transaction() as s:
        existing = svc.artifacts.get_chart(s, a, chart_id)
        c = svc.artifacts.save_chart(
            s,
            a,
            dataset_id=body.dataset_id,
            name=body.name,
            description=body.description,
            query=body.query,
            view=body.view,
            chart=existing,
        )
        return chart_out(c)


@router.delete("/charts/{chart_id}", status_code=204)
def delete_chart(
    chart_id: str, a: Actor = Depends(actor), svc: Services = Depends(services)
) -> None:
    with svc.db.transaction() as s:
        svc.artifacts.delete_chart(s, a, svc.artifacts.get_chart(s, a, chart_id))


@router.get("/charts/{chart_id}/render")
def render_chart(
    chart_id: str,
    theme: str | None = Query(default=None, pattern="^(light|dark)$"),
    width: int | None = Query(default=None, ge=200, le=4000),
    height: int | None = Query(default=None, ge=100, le=4000),
    a: Actor = Depends(actor),
    svc: Services = Depends(services),
) -> Response:
    with svc.db.transaction() as s:
        chart = svc.artifacts.get_chart(s, a, chart_id)
        r = svc.artifacts.render_chart(s, a, chart, theme=theme, width=width, height=height)
    return Response(content=r.svg, media_type=SVG, headers={"Cache-Control": "private, max-age=30"})


@router.get("/charts/{chart_id}/data")
def chart_data(
    chart_id: str, a: Actor = Depends(actor), svc: Services = Depends(services)
) -> dict[str, Any]:
    with svc.db.transaction() as s:
        chart = svc.artifacts.get_chart(s, a, chart_id)
        r = svc.artifacts.render_chart(s, a, chart)
        return {
            "columns": list(r.outcome.result.columns),
            "rows": jsonable_rows(r.outcome.result.rows),
            "total": r.outcome.result.row_count,
            "dataset_version": r.outcome.version.version,
            "plan_hash": r.outcome.result.plan_hash,
        }


@router.get("/charts/{chart_id}/export")
def export_chart(
    chart_id: str,
    format: str = Query(default="svg", pattern="^(svg|csv|xlsx)$"),
    theme: str | None = Query(default=None, pattern="^(light|dark)$"),
    a: Actor = Depends(actor),
    svc: Services = Depends(services),
) -> Response:
    with svc.db.transaction() as s:
        chart = svc.artifacts.get_chart(s, a, chart_id)
        r = svc.artifacts.render_chart(s, a, chart, theme=theme)
        audit.record(
            s,
            a,
            "chart.export",
            target_type="chart",
            target_id=chart.id,
            description=f"Exported chart {chart.name} as {format}",
            details={
                "dataset_version": r.outcome.version.version,
                "plan_hash": r.outcome.result.plan_hash,
            },
        )
        name = chart.name
    if format == "svg":
        body, media = r.svg.encode("utf-8"), SVG
    elif format == "xlsx":
        body = to_xlsx(list(r.outcome.result.columns), list(r.outcome.result.rows), sheet=name)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        body = to_csv(list(r.outcome.result.columns), list(r.outcome.result.rows))
        media = "text/csv; charset=utf-8"
    return Response(
        content=body,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{_filename(name, format)}"'},
    )


# ----------------------------------------------------------------------
# Dashboards
# ----------------------------------------------------------------------


@router.get("/dashboards")
def list_dashboards(
    a: Actor = Depends(actor), svc: Services = Depends(services)
) -> list[dict[str, Any]]:
    with svc.db.transaction() as s:
        return [dashboard_out(d) for d in svc.artifacts.list_dashboards(s, a)]


@router.post("/dashboards", status_code=201)
def create_dashboard(
    body: DashboardIn, a: Actor = Depends(actor), svc: Services = Depends(services)
) -> dict[str, Any]:
    from server.services.licensing import require_feature

    with svc.db.transaction() as s:
        require_feature(svc, s, "dashboards")
        d = svc.artifacts.save_dashboard(
            s,
            a,
            name=body.name,
            description=body.description,
            layout=[t.model_dump() for t in body.layout],
            filters=_filters(body),
        )
        return dashboard_out(d)


@router.get("/dashboards/{dashboard_id}")
def get_dashboard(
    dashboard_id: str, a: Actor = Depends(actor), svc: Services = Depends(services)
) -> dict[str, Any]:
    with svc.db.transaction() as s:
        d = svc.artifacts.get_dashboard(s, a, dashboard_id)
        out = dashboard_out(d)
        charts = {}
        for tile in d.layout:
            c = svc.artifacts.get_chart(s, a, tile["chart_id"])
            charts[c.id] = chart_out(c)
        out["charts"] = charts
        return out


@router.put("/dashboards/{dashboard_id}")
def update_dashboard(
    dashboard_id: str,
    body: DashboardIn,
    a: Actor = Depends(actor),
    svc: Services = Depends(services),
) -> dict[str, Any]:
    with svc.db.transaction() as s:
        existing = svc.artifacts.get_dashboard(s, a, dashboard_id)
        d = svc.artifacts.save_dashboard(
            s,
            a,
            name=body.name,
            description=body.description,
            layout=[t.model_dump() for t in body.layout],
            filters=_filters(body),
            dashboard=existing,
        )
        return dashboard_out(d)


@router.post("/dashboards/filter-fields")
def dashboard_filter_fields(
    body: FilterFieldsIn, a: Actor = Depends(actor), svc: Services = Depends(services)
) -> list[dict[str, Any]]:
    """Fields these charts' datasets have that a dashboard filter could use."""
    with svc.db.transaction() as s:
        return svc.artifacts.filter_field_summary(s, a, body.chart_ids)


@router.get("/dashboards/{dashboard_id}/filters/{index}/options")
def dashboard_filter_options(
    dashboard_id: str,
    index: int,
    a: Actor = Depends(actor),
    svc: Services = Depends(services),
) -> dict[str, Any]:
    """Distinct values (or the date span) a viewer can pick for one filter."""
    with svc.db.transaction() as s:
        d = svc.artifacts.get_dashboard(s, a, dashboard_id)
        return svc.artifacts.filter_options(s, a, d, index)


@router.get("/dashboards/{dashboard_id}/charts/{chart_id}/render")
def render_dashboard_chart(
    dashboard_id: str,
    chart_id: str,
    request: Request,
    theme: str | None = Query(default=None, pattern="^(light|dark)$"),
    width: int | None = Query(default=None, ge=200, le=4000),
    height: int | None = Query(default=None, ge=100, le=4000),
    a: Actor = Depends(actor),
    svc: Services = Depends(services),
) -> dict[str, Any]:
    """One tile, narrowed by the dashboard filters in the query string (fv0=…, ff1=…, ft1=…)
    and by a cross-filter from a click in another tile (xf=…&xv=…[&xg=…]&xc=<clicked chart>).
    """
    with svc.db.transaction() as s:
        d = svc.artifacts.get_dashboard(s, a, dashboard_id)
        if chart_id not in {t.get("chart_id") for t in d.layout}:
            raise NotFound("Chart is not on this dashboard")
        chart = svc.artifacts.get_chart(s, a, chart_id)
        items = request.query_params.multi_items()
        selections = parse_selections(d.filters or [], items)
        cross, source = parse_cross_filter(items)
        if cross is not None and source != chart_id:
            selections.append(cross)
        r = svc.artifacts.render_chart(
            s, a, chart, theme=theme, width=width, height=height, selections=selections
        )
    return {"svg": r.svg, "applied": list(r.applied), "skipped": list(r.skipped)}


@router.delete("/dashboards/{dashboard_id}", status_code=204)
def delete_dashboard(
    dashboard_id: str, a: Actor = Depends(actor), svc: Services = Depends(services)
) -> None:
    with svc.db.transaction() as s:
        svc.artifacts.delete_dashboard(s, a, svc.artifacts.get_dashboard(s, a, dashboard_id))


# ----------------------------------------------------------------------
# Shares
# ----------------------------------------------------------------------


@router.post("/shares", status_code=201)
def create_share(
    body: ShareIn, a: Actor = Depends(actor), svc: Services = Depends(services)
) -> dict[str, Any]:
    from server.services.licensing import require_feature

    with svc.db.transaction() as s:
        if body.allow_embed:
            require_feature(svc, s, "embed")
        share, token = svc.artifacts.create_share(
            s,
            a,
            artifact_type=body.artifact_type,
            artifact_id=body.artifact_id,
            expires_in_hours=body.expires_in_hours,
            allow_embed=body.allow_embed,
        )
        return share_out(share, svc.settings.base_url, token)


@router.get("/shares")
def list_shares(
    artifact_id: str | None = None, a: Actor = Depends(actor), svc: Services = Depends(services)
) -> list[dict[str, Any]]:
    with svc.db.transaction() as s:
        return [
            share_out(x, svc.settings.base_url)
            for x in svc.artifacts.list_shares(s, a, artifact_id)
        ]


@router.delete("/shares/{share_id}")
def revoke_share(
    share_id: str, a: Actor = Depends(actor), svc: Services = Depends(services)
) -> dict[str, Any]:
    with svc.db.transaction() as s:
        return share_out(svc.artifacts.revoke_share(s, a, share_id), svc.settings.base_url)
