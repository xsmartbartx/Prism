"""Workspace administration: members, invites, password resets, API keys."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from server.api.deps import Principal, principal, services
from server.api.serializers import apikey_out, invite_out, user_out, workspace_out
from server.container import Services
from server.db.models import ApiKey, Invite, Membership, Role, User, Workspace
from server.errors import BadRequest, NotFound
from server.services import audit
from server.services.auth import slugify

router = APIRouter(prefix="/api/v1/workspace", tags=["workspace"])


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class InviteIn(BaseModel):
    email: str = Field(max_length=320)
    role: Role = Role.VIEWER


class RoleIn(BaseModel):
    role: Role


class ApiKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


def _link(svc: Services, token: str) -> str:
    return f"{svc.settings.base_url.rstrip('/')}/invite/{token}"


@router.get("")
def get_workspace(
    p: Principal = Depends(principal), svc: Services = Depends(services)
) -> dict[str, Any]:
    with svc.db.transaction() as s:
        ws = s.get(Workspace, p.actor.workspace_id)
        assert ws is not None
        return workspace_out(ws, p.actor.role.value)


@router.patch("")
def rename_workspace(
    body: WorkspaceIn, p: Principal = Depends(principal), svc: Services = Depends(services)
) -> dict[str, Any]:
    p.actor.require("admin")
    with svc.db.transaction() as s:
        ws = s.get(Workspace, p.actor.workspace_id)
        assert ws is not None
        ws.name = body.name.strip()
        audit.record(
            s,
            p.actor,
            "workspace.update",
            target_type="workspace",
            target_id=ws.id,
            description=f"Renamed workspace to {ws.name}",
        )
        return workspace_out(ws, p.actor.role.value)


@router.post("/new", status_code=201)
def create_workspace(
    body: WorkspaceIn, p: Principal = Depends(principal), svc: Services = Depends(services)
) -> dict[str, Any]:
    from server.services.licensing import require_feature

    with svc.db.transaction() as s:
        require_feature(svc, s, "workspaces", current=len(p.memberships))
        slug = slugify(body.name)
        if s.scalars(select(Workspace).where(Workspace.slug == slug)).first():
            slug = f"{slug}-{p.user.id[:6]}"
        ws = Workspace(name=body.name.strip(), slug=slug)
        s.add(ws)
        s.flush()
        s.add(Membership(user_id=p.user.id, workspace_id=ws.id, role=Role.ADMIN.value))
        audit.record(
            s,
            p.actor,
            "workspace.create",
            target_type="workspace",
            target_id=ws.id,
            description=f"Created workspace {ws.name}",
            workspace_id=ws.id,
        )
        return workspace_out(ws, Role.ADMIN.value)


@router.get("/members")
def members(
    p: Principal = Depends(principal), svc: Services = Depends(services)
) -> list[dict[str, Any]]:
    with svc.db.transaction() as s:
        rows = s.execute(
            select(User, Membership.role)
            .join(Membership, Membership.user_id == User.id)
            .where(Membership.workspace_id == p.actor.workspace_id)
            .order_by(User.email)
        ).all()
        return [{**user_out(u), "role": role} for u, role in rows]


@router.patch("/members/{user_id}")
def change_role(
    user_id: str, body: RoleIn, p: Principal = Depends(principal), svc: Services = Depends(services)
) -> dict[str, Any]:
    p.actor.require("admin")
    with svc.db.transaction() as s:
        m = s.scalars(
            select(Membership).where(
                Membership.user_id == user_id, Membership.workspace_id == p.actor.workspace_id
            )
        ).first()
        if m is None:
            raise NotFound("Member not found")
        if m.role == Role.ADMIN.value and body.role != Role.ADMIN:
            admins = s.scalars(
                select(Membership).where(
                    Membership.workspace_id == p.actor.workspace_id,
                    Membership.role == Role.ADMIN.value,
                )
            ).all()
            if len(admins) <= 1:
                raise BadRequest("A workspace needs at least one admin")
        old, m.role = m.role, body.role.value
        audit.record(
            s,
            p.actor,
            "member.role",
            target_type="user",
            target_id=user_id,
            description=f"Changed role {old} → {m.role}",
        )
        return {"user_id": user_id, "role": m.role}


@router.delete("/members/{user_id}", status_code=204)
def remove_member(
    user_id: str, p: Principal = Depends(principal), svc: Services = Depends(services)
) -> None:
    p.actor.require("admin")
    with svc.db.transaction() as s:
        m = s.scalars(
            select(Membership).where(
                Membership.user_id == user_id, Membership.workspace_id == p.actor.workspace_id
            )
        ).first()
        if m is None:
            raise NotFound("Member not found")
        if m.role == Role.ADMIN.value:
            admins = s.scalars(
                select(Membership).where(
                    Membership.workspace_id == p.actor.workspace_id,
                    Membership.role == Role.ADMIN.value,
                )
            ).all()
            if len(admins) <= 1:
                raise BadRequest("A workspace needs at least one admin")
        s.delete(m)
        audit.record(
            s,
            p.actor,
            "member.remove",
            target_type="user",
            target_id=user_id,
            description="Removed member from workspace",
        )


@router.get("/invites")
def list_invites(
    p: Principal = Depends(principal), svc: Services = Depends(services)
) -> list[dict[str, Any]]:
    p.actor.require("admin")
    with svc.db.transaction() as s:
        rows = s.scalars(
            select(Invite)
            .where(Invite.workspace_id == p.actor.workspace_id, Invite.accepted_at.is_(None))
            .order_by(Invite.created_at.desc())
        ).all()
        return [invite_out(i) for i in rows]


@router.post("/invites", status_code=201)
def invite(
    body: InviteIn, p: Principal = Depends(principal), svc: Services = Depends(services)
) -> dict[str, Any]:
    from server.services.licensing import require_feature, seat_count

    with svc.db.transaction() as s:
        require_feature(svc, s, "users", current=seat_count(s))
        issued = svc.auth.create_invite(s, p.actor, body.email, body.role)
        inv = s.get(Invite, issued.record_id)
        assert inv is not None
        return {**invite_out(inv), "link": _link(svc, issued.secret)}


@router.delete("/invites/{invite_id}", status_code=204)
def revoke_invite(
    invite_id: str, p: Principal = Depends(principal), svc: Services = Depends(services)
) -> None:
    p.actor.require("admin")
    with svc.db.transaction() as s:
        inv = s.get(Invite, invite_id)
        if inv is None or inv.workspace_id != p.actor.workspace_id:
            raise NotFound("Invite not found")
        s.delete(inv)
        audit.record(
            s,
            p.actor,
            "invite.revoke",
            target_type="invite",
            target_id=invite_id,
            description=f"Revoked invite for {inv.email}",
        )


@router.post("/members/{user_id}/reset-link", status_code=201)
def reset_link(
    user_id: str, p: Principal = Depends(principal), svc: Services = Depends(services)
) -> dict[str, Any]:
    p.actor.require("admin")
    with svc.db.transaction() as s:
        m = s.scalars(
            select(Membership).where(
                Membership.user_id == user_id, Membership.workspace_id == p.actor.workspace_id
            )
        ).first()
        user = s.get(User, user_id)
        if m is None or user is None:
            raise NotFound("Member not found")
        issued = svc.auth.create_invite(
            s, p.actor, user.email, Role(m.role), kind="reset", hours=24
        )
        return {"link": _link(svc, issued.secret), "expires_in_hours": 24}


@router.get("/api-keys")
def list_keys(
    p: Principal = Depends(principal), svc: Services = Depends(services)
) -> list[dict[str, Any]]:
    with svc.db.transaction() as s:
        stmt = select(ApiKey).where(ApiKey.workspace_id == p.actor.workspace_id)
        if not p.actor.can("admin"):
            stmt = stmt.where(ApiKey.user_id == p.user.id)
        return [apikey_out(k) for k in s.scalars(stmt.order_by(ApiKey.created_at.desc()))]


@router.post("/api-keys", status_code=201)
def create_key(
    body: ApiKeyIn, p: Principal = Depends(principal), svc: Services = Depends(services)
) -> dict[str, Any]:
    from server.services.licensing import require_feature

    with svc.db.transaction() as s:
        require_feature(svc, s, "api")
        issued = svc.auth.create_api_key(s, p.actor, body.name)
        key = s.get(ApiKey, issued.record_id)
        assert key is not None
        return {**apikey_out(key), "secret": issued.secret}


@router.delete("/api-keys/{key_id}", status_code=204)
def revoke_key(
    key_id: str, p: Principal = Depends(principal), svc: Services = Depends(services)
) -> None:
    with svc.db.transaction() as s:
        svc.auth.revoke_api_key(s, p.actor, key_id)
