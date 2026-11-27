"""Datasets, charts and dashboards: CRUD, search, rendering and sharing."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from core.clock import utcnow
from data.load.store import DatasetStore
from data.query import QuerySpec
from data.query.spec import AggFunction, AggregationSpec, FilterSpec, SortSpec
from presentation.render.svg_renderer import SvgRenderer
from presentation.spec.view_spec import EncodingChannel, MarkType, ViewSpec, validate_view
from server.db.models import (
    Chart,
    Dashboard,
    Dataset,
    DatasetStatus,
    DatasetVersion,
    Share,
)
from server.errors import BadRequest, NotFound
from server.services import audit
from server.services.auth import sha256
from server.services.context import Actor
from server.services.dashboard_filters import (
    MAX_VALUE_CHARS,
    VALUE_LIMIT,
    VALUE_TYPES,
    Selection,
    apply_selections,
    clean_definitions,
    field_key,
    resolve_column,
)
from server.services.queries import QueryOutcome, QueryService, dataset_types

MAX_DASHBOARD_TILES = 48


def parse_specs(query: dict[str, Any], view: dict[str, Any]) -> tuple[QuerySpec, ViewSpec]:
    try:
        return QuerySpec.model_validate(query), ViewSpec.model_validate(view)
    except PydanticValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first.get("loc", ()))
        raise BadRequest(f"Invalid chart specification at '{loc}': {first.get('msg')}") from exc


@dataclass(frozen=True)
class RenderedChart:
    svg: str
    outcome: QueryOutcome
    view: ViewSpec
    # Dashboard filters (labels) that narrowed this chart, and those that could not apply to it.
    applied: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()


@dataclass(frozen=True)
class TileSource:
    chart: Chart
    dataset: Dataset
    column_types: dict[str, str]


class ArtifactService:
    def __init__(self, store: DatasetStore, queries: QueryService) -> None:
        self.store = store
        self.queries = queries
        self.renderer = SvgRenderer()

    # ------------------------------------------------------------------
    # Datasets
    # ------------------------------------------------------------------

    @staticmethod
    def get_dataset(s: Session, actor: Actor, dataset_id: str) -> Dataset:
        ds = s.get(Dataset, dataset_id)
        if ds is None or ds.workspace_id != actor.workspace_id:
            raise NotFound("Dataset not found")
        return ds

    @staticmethod
    def list_datasets(s: Session, actor: Actor, q: str = "", limit: int = 100) -> list[Dataset]:
        stmt = select(Dataset).where(Dataset.workspace_id == actor.workspace_id)
        if q:
            like = f"%{q.lower()}%"
            stmt = stmt.where(
                or_(func.lower(Dataset.name).like(like), func.lower(Dataset.description).like(like))
            )
        # Certified first, then most recently updated.
        stmt = stmt.order_by(
            (Dataset.status == DatasetStatus.CERTIFIED.value).desc(), Dataset.updated_at.desc()
        ).limit(limit)
        return list(s.scalars(stmt))

    def update_dataset(
        self, s: Session, actor: Actor, ds: Dataset, changes: dict[str, Any]
    ) -> Dataset:
        actor.require("author")
        if "status" in changes and changes["status"] != ds.status:
            actor.require("steward")
            status = changes["status"]
            if status not in {x.value for x in DatasetStatus}:
                raise BadRequest("Unknown status")
            if (
                status == DatasetStatus.CERTIFIED.value
                and not (changes.get("description", ds.description) or "").strip()
            ):
                raise BadRequest("A certified dataset needs a description")
            audit.record(
                s,
                actor,
                f"dataset.{status}",
                target_type="dataset",
                target_id=ds.id,
                description=f"{ds.name} marked {status}",
            )
            ds.status = status
        for key in ("name", "description", "tags"):
            if key in changes and changes[key] is not None:
                setattr(ds, key, changes[key])
        ds.updated_at = utcnow()
        audit.record(
            s,
            actor,
            "dataset.update",
            target_type="dataset",
            target_id=ds.id,
            description=f"Updated {ds.name}",
            details={k: v for k, v in changes.items() if k != "status"},
        )
        return ds

    def delete_dataset(self, s: Session, actor: Actor, ds: Dataset) -> None:
        actor.require("author")
        charts = s.scalars(select(Chart.id).where(Chart.dataset_id == ds.id)).all()
        for cid in charts:
            self._revoke_shares_for(s, "chart", cid)
        self._strip_from_dashboards(s, actor, set(charts))
        audit.record(
            s,
            actor,
            "dataset.delete",
            target_type="dataset",
            target_id=ds.id,
            description=f"Deleted dataset {ds.name}",
            details={"charts_deleted": len(charts)},
        )
        s.delete(ds)
        s.flush()
        self.store.delete_dataset(ds.workspace_id, ds.id)

    @staticmethod
    def versions(s: Session, ds: Dataset) -> list[DatasetVersion]:
        return list(
            s.scalars(
                select(DatasetVersion)
                .where(DatasetVersion.dataset_id == ds.id)
                .order_by(DatasetVersion.version.desc())
            )
        )

    def quarantine_rows(
        self, s: Session, actor: Actor, ds: Dataset, limit: int = 200
    ) -> list[dict[str, Any]]:
        actor.require("explore")
        version = self.queries.current_version(s, ds)
        if not version.quarantine_path:
            return []
        table = self.store.read(version.quarantine_path)
        rows: list[dict[str, Any]] = table.slice(0, limit).to_pylist()
        return rows

    # ------------------------------------------------------------------
    # Charts
    # ------------------------------------------------------------------

    @staticmethod
    def get_chart(s: Session, actor: Actor, chart_id: str) -> Chart:
        ch = s.get(Chart, chart_id)
        if ch is None or ch.workspace_id != actor.workspace_id:
            raise NotFound("Chart not found")
        return ch

    @staticmethod
    def list_charts(
        s: Session, actor: Actor, *, dataset_id: str | None = None, q: str = ""
    ) -> list[Chart]:
        stmt = select(Chart).where(Chart.workspace_id == actor.workspace_id)
        if dataset_id:
            stmt = stmt.where(Chart.dataset_id == dataset_id)
        if q:
            stmt = stmt.where(func.lower(Chart.name).like(f"%{q.lower()}%"))
        return list(s.scalars(stmt.order_by(Chart.updated_at.desc()).limit(200)))

    def validate_chart(
        self, s: Session, actor: Actor | None, ds: Dataset, query: QuerySpec, view: ViewSpec
    ) -> QueryOutcome:
        if view.mark == MarkType.PIVOT and (pivot_errors := _pivot_query_errors(query, view)):
            raise BadRequest("; ".join(pivot_errors))
        if view.mark == MarkType.KPI and (kpi_errors := _kpi_query_errors(query, view)):
            raise BadRequest("; ".join(kpi_errors))
        outcome = self.queries.run(s, actor, ds, query)
        errors = validate_view(view, list(outcome.result.columns))
        if errors:
            raise BadRequest("; ".join(errors))
        return outcome

    def render(
        self,
        s: Session,
        actor: Actor | None,
        ds: Dataset,
        query: QuerySpec,
        view: ViewSpec,
        *,
        overrides: dict[str, Any] | None = None,
    ) -> RenderedChart:
        outcome = self.validate_chart(s, actor, ds, query, view)
        update = dict(overrides or {})
        if view.mark == MarkType.PIVOT:
            update["total_function"] = _pivot_totals(query) if view.totals else None
        if view.mark == MarkType.KPI and view.encoding_for(EncodingChannel.X):
            # "Today" for leaving out the period still in progress; the renderer has no clock.
            update["as_of"] = utcnow().date().isoformat() if view.complete_periods else None
        grain = _category_grain(query, view)
        if grain and not view.time_grain:
            # The query buckets the category axis by time but the view does not say so (charts
            # saved through the API): label the buckets, and let a click select the whole bucket.
            update["time_grain"] = grain
        if update:
            view = view.model_copy(update=update)
        svg = self.renderer.render(view, list(outcome.result.rows))
        return RenderedChart(svg=svg, outcome=outcome, view=view)

    def save_chart(
        self,
        s: Session,
        actor: Actor,
        *,
        dataset_id: str,
        name: str,
        description: str,
        query: dict[str, Any],
        view: dict[str, Any],
        chart: Chart | None = None,
    ) -> Chart:
        actor.require("explore")
        ds = self.get_dataset(s, actor, dataset_id)
        qspec, vspec = parse_specs(query, view)
        self.validate_chart(s, actor, ds, qspec, vspec)
        qdoc, vdoc = qspec.model_dump(mode="json"), vspec.model_dump(mode="json")
        if chart is None:
            chart = Chart(
                workspace_id=actor.workspace_id,
                dataset_id=ds.id,
                name=name.strip() or "Untitled chart",
                description=description,
                query_spec=qdoc,
                view_spec=vdoc,
                owner_id=actor.user_id,
            )
            s.add(chart)
            s.flush()
            action = "chart.create"
        else:
            if chart.owner_id != actor.user_id:
                actor.require("author")
            chart.dataset_id = ds.id
            chart.name = name.strip() or chart.name
            chart.description = description
            chart.query_spec, chart.view_spec = qdoc, vdoc
            chart.updated_at = utcnow()
            action = "chart.update"
        version = self.queries.current_version(s, ds)
        audit.record(
            s,
            actor,
            action,
            target_type="chart",
            target_id=chart.id,
            description=f"Saved chart {chart.name}",
            details={
                "dataset_id": ds.id,
                "dataset_version": version.version,
                "dataset_content_hash": version.content_hash,
                "query": qdoc,
                "view": vdoc,
            },
        )
        return chart

    def delete_chart(self, s: Session, actor: Actor, chart: Chart) -> None:
        if chart.owner_id != actor.user_id:
            actor.require("author")
        else:
            actor.require("explore")
        self._revoke_shares_for(s, "chart", chart.id)
        self._strip_from_dashboards(s, actor, {chart.id})
        audit.record(
            s,
            actor,
            "chart.delete",
            target_type="chart",
            target_id=chart.id,
            description=f"Deleted chart {chart.name}",
        )
        s.delete(chart)

    def render_chart(
        self,
        s: Session,
        actor: Actor | None,
        chart: Chart,
        *,
        theme: str | None = None,
        width: int | None = None,
        height: int | None = None,
        selections: list[Selection] | None = None,
    ) -> RenderedChart:
        ds = s.get(Dataset, chart.dataset_id)
        if ds is None:
            raise NotFound("The chart's dataset no longer exists")
        q, v = parse_specs(chart.query_spec, chart.view_spec)
        applied: list[str] = []
        skipped: list[str] = []
        if selections:
            types = dataset_types(ds, self.queries.current_version(s, ds))
            q, applied, skipped = apply_selections(q, types, selections)
        overrides: dict[str, Any] = {}
        if theme in ("light", "dark"):
            overrides["theme"] = theme
        if width:
            overrides["width"] = max(200, min(width, 4000))
        if height:
            overrides["height"] = max(100, min(height, 4000))
        r = self.render(s, actor, ds, q, v, overrides=overrides or None)
        if not (applied or skipped):
            return r
        return RenderedChart(
            svg=r.svg,
            outcome=r.outcome,
            view=r.view,
            applied=tuple(applied),
            skipped=tuple(skipped),
        )

    # ------------------------------------------------------------------
    # Dashboards
    # ------------------------------------------------------------------

    @staticmethod
    def get_dashboard(s: Session, actor: Actor, dashboard_id: str) -> Dashboard:
        d = s.get(Dashboard, dashboard_id)
        if d is None or d.workspace_id != actor.workspace_id:
            raise NotFound("Dashboard not found")
        return d

    @staticmethod
    def list_dashboards(s: Session, actor: Actor) -> list[Dashboard]:
        return list(
            s.scalars(
                select(Dashboard)
                .where(Dashboard.workspace_id == actor.workspace_id)
                .order_by(Dashboard.updated_at.desc())
            )
        )

    def _clean_layout(
        self, s: Session, actor: Actor, layout: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if len(layout) > MAX_DASHBOARD_TILES:
            raise BadRequest(f"A dashboard holds at most {MAX_DASHBOARD_TILES} tiles")
        clean = []
        for tile in layout:
            cid = str(tile.get("chart_id", ""))
            self.get_chart(s, actor, cid)
            clean.append(
                {
                    "chart_id": cid,
                    "x": max(0, min(int(tile.get("x", 0)), 11)),
                    "y": max(0, min(int(tile.get("y", 0)), 1000)),
                    "w": max(1, min(int(tile.get("w", 6)), 12)),
                    "h": max(1, min(int(tile.get("h", 4)), 20)),
                }
            )
        return clean

    def save_dashboard(
        self,
        s: Session,
        actor: Actor,
        *,
        name: str,
        description: str,
        layout: list[dict[str, Any]],
        filters: list[dict[str, Any]] | None = None,
        dashboard: Dashboard | None = None,
    ) -> Dashboard:
        """Create or update a dashboard.

        ``filters`` replaces the dashboard's filters and must name fields its tiles have.
        Left out (None), the existing filters are kept, minus any that no longer fit the
        tiles (a removed chart takes its fields with it, or leaves a field of another type):
        a layout change never fails over filters the caller did not send.
        """
        actor.require("explore")
        clean = self._clean_layout(s, actor, layout)
        fields = self.filter_fields(s, actor.workspace_id, clean)
        if filters is not None:
            clean_filters = clean_definitions(filters, fields)
        else:
            clean_filters = []
            for f in (dashboard.filters if dashboard else None) or []:
                try:
                    clean_filters += clean_definitions([*clean_filters, f], fields)[-1:]
                except BadRequest:
                    continue
        if dashboard is None:
            dashboard = Dashboard(
                workspace_id=actor.workspace_id,
                name=name.strip() or "Untitled",
                description=description,
                layout=clean,
                filters=clean_filters,
                owner_id=actor.user_id,
            )
            s.add(dashboard)
            s.flush()
            action = "dashboard.create"
        else:
            if dashboard.owner_id != actor.user_id:
                actor.require("author")
            dashboard.name = name.strip() or dashboard.name
            dashboard.description = description
            dashboard.layout = clean
            dashboard.filters = clean_filters
            dashboard.updated_at = utcnow()
            action = "dashboard.update"
        audit.record(
            s,
            actor,
            action,
            target_type="dashboard",
            target_id=dashboard.id,
            description=f"Saved dashboard {dashboard.name}",
            details={"tiles": len(clean), "filters": [f["field"] for f in clean_filters]},
        )
        return dashboard

    # ------------------------------------------------------------------
    # Dashboard filters
    # ------------------------------------------------------------------

    def tile_sources(
        self, s: Session, workspace_id: str, layout: list[dict[str, Any]]
    ) -> list[TileSource]:
        """Each tile's chart, dataset and current column types (tiles without data skipped)."""
        out: list[TileSource] = []
        for tile in layout:
            chart = s.get(Chart, str(tile.get("chart_id", "")))
            if chart is None or chart.workspace_id != workspace_id:
                continue
            ds = s.get(Dataset, chart.dataset_id)
            version = s.get(DatasetVersion, ds.current_version_id) if ds else None
            if ds is None or version is None or version.dataset_id != ds.id:
                continue
            out.append(TileSource(chart=chart, dataset=ds, column_types=dataset_types(ds, version)))
        return out

    def filter_fields(
        self, s: Session, workspace_id: str, layout: list[dict[str, Any]]
    ) -> dict[str, set[str]]:
        """Every column name the tiles' datasets have, with the types it has there."""
        fields: dict[str, set[str]] = {}
        for src in self.tile_sources(s, workspace_id, layout):
            for name, col_type in src.column_types.items():
                fields.setdefault(name, set()).add(col_type)
        return fields

    def filter_field_summary(
        self, s: Session, actor: Actor, chart_ids: list[str]
    ) -> list[dict[str, Any]]:
        """Fields an editor can offer as filters for these charts, most widely shared first."""
        layout = [{"chart_id": self.get_chart(s, actor, c).id} for c in dict.fromkeys(chart_ids)]
        counts: dict[str, int] = {}
        types: dict[str, set[str]] = {}
        names: dict[str, str] = {}  # key -> the spelling first seen
        for src in self.tile_sources(s, actor.workspace_id, layout):
            for column, col_type in src.column_types.items():
                key = field_key(column)
                name = names.setdefault(key, column)
                counts[name] = counts.get(name, 0) + 1
                types.setdefault(name, set()).add(col_type)
        rows: list[dict[str, Any]] = []
        for name in sorted(counts, key=lambda n: (-counts[n], n.lower())):
            kinds = []
            if types[name] & VALUE_TYPES:
                kinds.append("values")
            if "date" in types[name]:
                kinds.append("date_range")
            if kinds:
                rows.append(
                    {
                        "field": name,
                        "types": sorted(types[name]),
                        "charts": counts[name],
                        "kinds": kinds,
                    }
                )
        return rows

    def filter_options(
        self, s: Session, actor: Actor | None, dashboard: Dashboard, index: int
    ) -> dict[str, Any]:
        """What a viewer can pick for one filter: distinct values, or a date span.

        Values come only from rows the tiles themselves aggregate: each tile's own filters
        are part of its options query. A share page is anonymous, so a picker must not reveal
        values from rows a shared chart deliberately leaves out. Tiles over the same dataset
        with the same filters are queried once; different filters are queried separately and
        their results merged.
        """
        definitions = dashboard.filters or []
        if not 0 <= index < len(definitions):
            raise NotFound("Filter not found")
        d = definitions[index]
        field, kind = d["field"], d["kind"]
        out: dict[str, Any] = {"field": field, "kind": kind, "label": d.get("label") or field}
        sources: list[tuple[TileSource, str, list[FilterSpec]]] = []
        seen: set[tuple[str, str]] = set()
        for src in self.tile_sources(s, dashboard.workspace_id, dashboard.layout):
            column = resolve_column(field, src.column_types)
            if column is None:
                continue
            own, _ = parse_specs(src.chart.query_spec, src.chart.view_spec)
            key = (
                src.dataset.id,
                json.dumps([f.model_dump(mode="json") for f in own.filters], sort_keys=True),
            )
            if key not in seen:
                seen.add(key)
                sources.append((src, column, list(own.filters)))

        if kind == "date_range":
            lows, highs = [], []
            for src, column, own_filters in sources:
                if src.column_types[column] != "date":
                    continue
                q = QuerySpec(
                    measures=[
                        AggregationSpec(column=column, function=AggFunction.MIN, alias="lo"),
                        AggregationSpec(column=column, function=AggFunction.MAX, alias="hi"),
                    ],
                    filters=own_filters,
                )
                row = self.queries.run(s, actor, src.dataset, q).result.rows[0]
                if row.get("lo") is not None:
                    lows.append(row["lo"])
                    highs.append(row["hi"])
            out["min"] = min(lows).isoformat() if lows else None
            out["max"] = max(highs).isoformat() if highs else None
            return out

        # Keyed by the text a selection sends back, so True and 1 stay two options.
        options: dict[str, tuple[str, Any]] = {}
        truncated = False
        too_long = 0
        for src, column, own_filters in sources:
            # The count only makes this a grouped query; name it apart from the field.
            alias = "__count" if column != "__count" else "__count_"
            q = QuerySpec(
                dimensions=[column],
                measures=[AggregationSpec(column="*", function=AggFunction.COUNT, alias=alias)],
                filters=own_filters,
                sort=[SortSpec(column=column)],
                limit=VALUE_LIMIT + 1,
            )
            rows = self.queries.run(s, actor, src.dataset, q).result.rows
            truncated |= len(rows) > VALUE_LIMIT
            for r in rows[:VALUE_LIMIT]:
                v = r[column]
                if v is None:
                    continue
                text = _option_text(v)
                if len(text.strip()) > MAX_VALUE_CHARS:
                    too_long += 1  # a selection that long is not accepted, so do not offer it
                    continue
                options.setdefault(text, (type(v).__name__, v))
        ordered = sorted(options, key=lambda t: options[t])
        out["truncated"] = truncated or len(ordered) > VALUE_LIMIT
        out["values"] = ordered[:VALUE_LIMIT]
        out["omitted_long"] = too_long
        return out

    def delete_dashboard(self, s: Session, actor: Actor, dashboard: Dashboard) -> None:
        if dashboard.owner_id != actor.user_id:
            actor.require("author")
        self._revoke_shares_for(s, "dashboard", dashboard.id)
        audit.record(
            s,
            actor,
            "dashboard.delete",
            target_type="dashboard",
            target_id=dashboard.id,
            description=f"Deleted dashboard {dashboard.name}",
        )
        s.delete(dashboard)

    @staticmethod
    def _strip_from_dashboards(s: Session, actor: Actor, chart_ids: set[str]) -> None:
        if not chart_ids:
            return
        for d in s.scalars(select(Dashboard).where(Dashboard.workspace_id == actor.workspace_id)):
            kept = [t for t in d.layout if t.get("chart_id") not in chart_ids]
            if len(kept) != len(d.layout):
                d.layout = kept

    # ------------------------------------------------------------------
    # Sharing
    # ------------------------------------------------------------------

    def create_share(
        self,
        s: Session,
        actor: Actor,
        *,
        artifact_type: str,
        artifact_id: str,
        expires_in_hours: int | None,
        allow_embed: bool,
    ) -> tuple[Share, str]:
        actor.require("explore")
        if artifact_type == "chart":
            self.get_chart(s, actor, artifact_id)
        elif artifact_type == "dashboard":
            self.get_dashboard(s, actor, artifact_id)
        else:
            raise BadRequest("Only charts and dashboards can be shared")
        token = secrets.token_urlsafe(24)
        share = Share(
            workspace_id=actor.workspace_id,
            token_hash=sha256(token),
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            created_by=actor.user_id,
            expires_at=utcnow() + timedelta(hours=expires_in_hours) if expires_in_hours else None,
            allow_embed=allow_embed,
        )
        s.add(share)
        s.flush()
        audit.record(
            s,
            actor,
            "share.create",
            target_type=artifact_type,
            target_id=artifact_id,
            description=f"Created a public link for {artifact_type} {artifact_id}",
            details={"share_id": share.id, "expires_at": share.expires_at, "embed": allow_embed},
        )
        return share, token

    @staticmethod
    def list_shares(s: Session, actor: Actor, artifact_id: str | None = None) -> list[Share]:
        stmt = select(Share).where(Share.workspace_id == actor.workspace_id)
        if artifact_id:
            stmt = stmt.where(Share.artifact_id == artifact_id)
        return list(s.scalars(stmt.order_by(Share.created_at.desc())))

    @staticmethod
    def revoke_share(s: Session, actor: Actor, share_id: str) -> Share:
        share = s.get(Share, share_id)
        if share is None or share.workspace_id != actor.workspace_id:
            raise NotFound("Share not found")
        if share.created_by != actor.user_id:
            actor.require("author")
        share.revoked_at = utcnow()
        audit.record(
            s,
            actor,
            "share.revoke",
            target_type=share.artifact_type,
            target_id=share.artifact_id,
            description="Revoked a public link",
            details={"share_id": share.id},
        )
        return share

    @staticmethod
    def resolve_share(s: Session, token: str, *, count_use: bool = True) -> Share:
        share = s.scalars(select(Share).where(Share.token_hash == sha256(token))).first()
        now = utcnow()
        if (
            share is None
            or share.revoked_at is not None
            or (share.expires_at is not None and share.expires_at <= now)
            or (share.max_uses is not None and share.use_count >= share.max_uses)
        ):
            raise NotFound("This link is invalid, expired or revoked")
        if count_use:
            share.use_count += 1
            share.last_used_at = now
        return share

    @staticmethod
    def _revoke_shares_for(s: Session, artifact_type: str, artifact_id: str) -> None:
        now = utcnow()
        for sh in s.scalars(
            select(Share).where(
                Share.artifact_type == artifact_type,
                Share.artifact_id == artifact_id,
                Share.revoked_at.is_(None),
            )
        ):
            sh.revoked_at = now


def _option_text(value: Any) -> str:
    """A picker value as the text a selection sends back (and the compiler can coerce)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


def _category_grain(query: QuerySpec, view: ViewSpec) -> str | None:
    """The time grain the query applies to the chart's category field, if any."""
    enc = view.encoding_for(EncodingChannel.X)
    if view.mark == MarkType.PIE:
        enc = view.encoding_for(EncodingChannel.COLOR) or enc
    if enc is None:
        return None
    grain = query.time_grain.get(enc.field)
    return grain.value if grain is not None else None


def _kpi_query_errors(query: QuerySpec, view: ViewSpec) -> list[str]:
    """A KPI over time needs one row per period: one value, grouped by its date field only."""
    xe = view.encoding_for(EncodingChannel.X)
    if xe is None:
        return []
    if query.columns or len(query.measures) != 1:
        return ["A KPI over time shows one value per period: pick one value"]
    if list(query.dimensions) != [xe.field]:
        return [f"A KPI over time groups by its date field ({xe.field}) only"]
    if xe.field not in query.time_grain:
        return [f"Pick a time bucket (day, week, month, quarter or year) for {xe.field}"]
    return []


def _pivot_query_errors(query: QuerySpec, view: ViewSpec) -> list[str]:
    """A pivot needs one row per cell: grouped by its rows and columns fields and nothing else.

    Ungrouped rows, or a grouping by a further field, give several rows for one cell, and the
    table would show only one of them.
    """
    if query.columns or not query.measures:
        return ["A pivot table needs grouped data: group by its rows and columns with one value"]
    axes = (EncodingChannel.X, EncodingChannel.COLOR)
    fields = {e.field for e in view.encodings if e.channel in axes}
    extra = [d for d in query.dimensions if d not in fields]
    if extra:
        return [
            "A pivot table groups by its rows and columns only; remove "
            + ", ".join(extra)
            + " from the grouping or use it as a filter"
        ]
    return []


def _pivot_totals(query: QuerySpec) -> str | None:
    """How a pivot's cells combine into correct totals, if they do.

    Sums and counts add up; a minimum or maximum of cells is the group's; an average, a
    median, a distinct count or a calculated measure of cells is not the group's, so no
    totals are shown rather than wrong ones.
    """
    if len(query.measures) != 1:
        return None
    fn = query.measures[0].function
    if fn in (AggFunction.SUM, AggFunction.COUNT):
        return "sum"
    if fn == AggFunction.MIN:
        return "min"
    if fn == AggFunction.MAX:
        return "max"
    return None
