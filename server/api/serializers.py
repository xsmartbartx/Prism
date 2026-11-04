"""Model → JSON dictionaries returned by the API."""

from __future__ import annotations

from typing import Any

from server.db.models import (
    ApiKey,
    AuditEvent,
    Chart,
    Dashboard,
    Dataset,
    DatasetVersion,
    Import,
    Invite,
    Share,
    User,
    Workspace,
)


def user_out(u: User) -> dict[str, Any]:
    return {
        "id": u.id,
        "email": u.email,
        "name": u.name,
        "is_active": u.is_active,
        "is_superadmin": u.is_superadmin,
        "created_at": u.created_at,
        "last_login_at": u.last_login_at,
    }


def workspace_out(w: Workspace, role: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"id": w.id, "name": w.name, "slug": w.slug, "created_at": w.created_at}
    if role:
        out["role"] = role
    return out


def import_out(i: Import) -> dict[str, Any]:
    return {
        "id": i.id,
        "filename": i.filename,
        "file_kind": i.file_kind,
        "size_bytes": i.size_bytes,
        "sha256": i.sha256,
        "status": i.status,
        "sheet_names": i.sheet_names,
        "proposal": i.proposal,
        "error": i.error,
        "dataset_id": i.dataset_id,
        "created_at": i.created_at,
    }


def version_out(v: DatasetVersion) -> dict[str, Any]:
    return {
        "id": v.id,
        "version": v.version,
        "row_count": v.row_count,
        "quarantine_count": v.quarantine_count,
        "content_hash": v.content_hash,
        "source_sha256": v.source_sha256,
        "binding_id": v.binding_id,
        "columns": v.columns,
        "profile": v.profile,
        "created_at": v.created_at,
    }


def dataset_out(d: Dataset, version: DatasetVersion | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": d.id,
        "name": d.name,
        "description": d.description,
        "tags": d.tags,
        "status": d.status,
        "owner_id": d.owner_id,
        "current_version_id": d.current_version_id,
        "created_at": d.created_at,
        "updated_at": d.updated_at,
    }
    if version is not None:
        out["current_version"] = version_out(version)
        out["row_count"] = version.row_count
        out["column_count"] = len(version.columns)
    return out


def chart_out(c: Chart) -> dict[str, Any]:
    return {
        "id": c.id,
        "dataset_id": c.dataset_id,
        "name": c.name,
        "description": c.description,
        "query": c.query_spec,
        "view": c.view_spec,
        "owner_id": c.owner_id,
        "created_at": c.created_at,
        "updated_at": c.updated_at,
    }


def dashboard_out(d: Dashboard) -> dict[str, Any]:
    return {
        "id": d.id,
        "name": d.name,
        "description": d.description,
        "layout": d.layout,
        "owner_id": d.owner_id,
        "created_at": d.created_at,
        "updated_at": d.updated_at,
    }


def share_out(s: Share, base_url: str, token: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": s.id,
        "artifact_type": s.artifact_type,
        "artifact_id": s.artifact_id,
        "created_by": s.created_by,
        "created_at": s.created_at,
        "expires_at": s.expires_at,
        "revoked_at": s.revoked_at,
        "use_count": s.use_count,
        "last_used_at": s.last_used_at,
        "allow_embed": s.allow_embed,
        "active": s.revoked_at is None,
    }
    if token:
        base = base_url.rstrip("/")
        out["token"] = token
        out["url"] = f"{base}/s/{token}"
        if s.allow_embed:
            out["embed_url"] = f"{base}/embed/{token}"
    return out


def audit_out(e: AuditEvent) -> dict[str, Any]:
    return {
        "id": e.id,
        "seq": e.seq,
        "timestamp": e.timestamp,
        "actor_id": e.actor_id,
        "actor": e.actor_label,
        "action": e.action,
        "target_type": e.target_type,
        "target_id": e.target_id,
        "description": e.description,
        "details": e.details,
        "ip": e.ip,
        "hash": e.hash,
    }


def apikey_out(k: ApiKey) -> dict[str, Any]:
    return {
        "id": k.id,
        "name": k.name,
        "prefix": k.prefix,
        "created_at": k.created_at,
        "last_used_at": k.last_used_at,
        "revoked_at": k.revoked_at,
    }


def invite_out(i: Invite) -> dict[str, Any]:
    return {
        "id": i.id,
        "email": i.email,
        "role": i.role,
        "kind": i.kind,
        "created_at": i.created_at,
        "expires_at": i.expires_at,
        "accepted_at": i.accepted_at,
    }
