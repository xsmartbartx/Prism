"""Health, readiness, version and audit endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, text

from server import __version__
from server.api.deps import actor, services
from server.api.serializers import audit_out
from server.container import Services
from server.db.models import AuditEvent
from server.services import audit
from server.services.context import Actor

router = APIRouter(tags=["system"])


@router.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
def readyz(svc: Services = Depends(services)) -> dict[str, Any]:
    with svc.db.transaction() as s:
        s.execute(text("SELECT 1"))
    writable = svc.settings.data_dir.exists() and svc.settings.datasets_dir.exists()
    return {"status": "ready" if writable else "degraded", "storage": writable}


@router.get("/api/v1/version")
def version() -> dict[str, str]:
    return {"version": __version__, "name": "Prism"}


@router.get("/api/v1/audit", tags=["audit"])
def audit_log(
    target_id: str | None = None,
    action: str | None = Query(default=None, max_length=40),
    before: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    a: Actor = Depends(actor),
    svc: Services = Depends(services),
) -> dict[str, Any]:
    a.require("audit")
    with svc.db.transaction() as s:
        stmt = select(AuditEvent).where(AuditEvent.workspace_id == a.workspace_id)
        if target_id:
            stmt = stmt.where(AuditEvent.target_id == target_id)
        if action:
            stmt = stmt.where(AuditEvent.action.like(f"{action}%"))
        if before:
            stmt = stmt.where(AuditEvent.seq < before)
        events = list(s.scalars(stmt.order_by(AuditEvent.seq.desc()).limit(limit)))
        return {
            "events": [audit_out(e) for e in events],
            "next_before": events[-1].seq if len(events) == limit else None,
        }


@router.get("/api/v1/audit/verify", tags=["audit"])
def audit_verify(a: Actor = Depends(actor), svc: Services = Depends(services)) -> dict[str, Any]:
    a.require("audit")
    with svc.db.transaction() as s:
        ok, broken, n = audit.verify_chain(s)
        return {"ok": ok, "first_broken_seq": broken, "events_checked": n}
