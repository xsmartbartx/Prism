"""Append-only, hash-chained audit log.

Each event stores the hash of its predecessor, so deleting or editing
any historical row breaks the chain detectably (``verify_chain``).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from core.clock import utcnow
from server.db.models import AuditEvent, new_id
from server.services.context import Actor


def _digest(prev_hash: str, ev: AuditEvent) -> str:
    body = {
        "id": ev.id,
        "workspace_id": ev.workspace_id,
        "timestamp": ev.timestamp.isoformat(),
        "actor_id": ev.actor_id,
        "actor_label": ev.actor_label,
        "action": ev.action,
        "target_type": ev.target_type,
        "target_id": ev.target_id,
        "description": ev.description,
        "details": ev.details,
    }
    raw = prev_hash + json.dumps(body, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def record(
    s: Session,
    actor: Actor | None,
    action: str,
    *,
    target_type: str | None = None,
    target_id: str | None = None,
    description: str = "",
    details: dict[str, Any] | None = None,
    workspace_id: str | None = None,
) -> AuditEvent:
    """Append one event to the chain (within the caller's transaction)."""
    if s.get_bind().dialect.name == "postgresql":
        s.execute(text("SELECT pg_advisory_xact_lock(7243901)"))
    prev = s.scalars(select(AuditEvent.hash).order_by(AuditEvent.seq.desc()).limit(1)).first()
    ev = AuditEvent(
        id=new_id(),
        workspace_id=workspace_id or (actor.workspace_id if actor else None),
        timestamp=utcnow(),
        actor_id=actor.user_id if actor else None,
        actor_label=actor.label if actor else "system",
        action=action,
        target_type=target_type,
        target_id=target_id,
        description=description,
        details=details or {},
        ip=actor.ip if actor else None,
        prev_hash=prev or "",
    )
    ev.hash = _digest(ev.prev_hash, ev)
    s.add(ev)
    s.flush()
    return ev


def verify_chain(s: Session) -> tuple[bool, int | None, int]:
    """Return ``(ok, first_broken_seq, events_checked)``."""
    prev = ""
    n = 0
    for ev in s.scalars(select(AuditEvent).order_by(AuditEvent.seq)):
        n += 1
        if ev.prev_hash != prev or _digest(prev, ev) != ev.hash:
            return False, ev.seq, n
        prev = ev.hash
    return True, None, n
