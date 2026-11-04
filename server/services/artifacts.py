"""Datasets, charts and dashboards: CRUD, search, rendering and sharing."""

from __future__ import annotations

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
from presentation.render.svg_renderer import SvgRenderer
from presentation.spec.view_spec import ViewSpec, validate_view
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
from server.services.queries import QueryOutcome, QueryService

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
        if overrides:
            view = view.model_copy(update=overrides)
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
    ) -> RenderedChart:
        ds = s.get(Dataset, chart.dataset_id)
        if ds is None:
            raise NotFound("The chart's dataset no longer exists")
        q, v = parse_specs(chart.query_spec, chart.view_spec)
        overrides: dict[str, Any] = {}
        if theme in ("light", "dark"):
            overrides["theme"] = theme
        if width:
            overrides["width"] = max(200, min(width, 4000))
        if height:
            overrides["height"] = max(100, min(height, 4000))
        return self.render(s, actor, ds, q, v, overrides=overrides or None)

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
        dashboard: Dashboard | None = None,
    ) -> Dashboard:
        actor.require("explore")
        clean = self._clean_layout(s, actor, layout)
        if dashboard is None:
            dashboard = Dashboard(
                workspace_id=actor.workspace_id,
                name=name.strip() or "Untitled",
                description=description,
                layout=clean,
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
            dashboard.updated_at = utcnow()
            action = "dashboard.update"
        audit.record(
            s,
            actor,
            action,
            target_type="dashboard",
            target_id=dashboard.id,
            description=f"Saved dashboard {dashboard.name}",
            details={"tiles": len(clean)},
        )
        return dashboard

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
