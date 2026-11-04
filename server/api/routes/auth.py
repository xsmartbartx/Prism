"""Setup, sign-in, session and profile endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from server.api.deps import (
    SESSION_COOKIE,
    Principal,
    client_ip,
    optional_principal,
    principal,
    services,
)
from server.api.serializers import user_out, workspace_out
from server.container import Services
from server.errors import Unauthorized
from server.services.auth import AuthService

router = APIRouter(prefix="/api/v1", tags=["auth"])


class SetupIn(BaseModel):
    email: str = Field(max_length=320)
    name: str = Field(default="", max_length=200)
    password: str = Field(max_length=256)
    workspace_name: str = Field(default="My workspace", max_length=200)


class LoginIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)


class PasswordIn(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class AcceptIn(BaseModel):
    name: str = Field(default="", max_length=200)
    password: str = Field(max_length=256)


def _set_cookie(response: Response, svc: Services, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=svc.settings.session_hours * 3600,
        httponly=True,
        secure=svc.settings.secure_cookies,
        samesite="lax",
        path="/",
    )


def me_payload(p: Principal) -> dict[str, Any]:
    return {
        "user": user_out(p.user),
        "workspace": workspace_out(
            next(ws for ws, _ in p.memberships if ws.id == p.actor.workspace_id),
            p.actor.role.value,
        ),
        "workspaces": [workspace_out(ws, role.value) for ws, role in p.memberships],
        "role": p.actor.role.value,
        "via": p.actor.via,
    }


@router.get("/setup/status")
def setup_status(svc: Services = Depends(services)) -> dict[str, Any]:
    with svc.db.transaction() as s:
        return {"needs_setup": AuthService.needs_setup(s)}


@router.post("/setup", status_code=201)
def setup(
    body: SetupIn, request: Request, response: Response, svc: Services = Depends(services)
) -> dict[str, Any]:
    with svc.db.transaction() as s:
        user, ws = svc.auth.setup(
            s,
            email=body.email,
            name=body.name,
            password=body.password,
            workspace_name=body.workspace_name,
        )
    with svc.db.transaction() as s:
        issued = svc.auth.login(
            s,
            user.email,
            body.password,
            ip=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    _set_cookie(response, svc, issued.token)
    return {"user": user_out(user), "workspace": workspace_out(ws, "admin")}


@router.post("/auth/login")
def login(
    body: LoginIn, request: Request, response: Response, svc: Services = Depends(services)
) -> dict[str, Any]:
    s = svc.db.session()
    try:
        issued = svc.auth.login(
            s,
            body.email,
            body.password,
            ip=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        s.commit()
    except Unauthorized:
        s.commit()  # keep the failed-attempt audit record
        raise
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
    _set_cookie(response, svc, issued.token)
    return {"ok": True}


@router.post("/auth/logout")
def logout(
    request: Request, response: Response, svc: Services = Depends(services)
) -> dict[str, Any]:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with svc.db.transaction() as s:
            svc.auth.logout(s, token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/auth/me")
def me(p: Principal | None = Depends(optional_principal)) -> dict[str, Any]:
    if p is None:
        raise Unauthorized("Sign in required")
    return me_payload(p)


@router.patch("/auth/me")
def update_profile(
    body: ProfileIn, p: Principal = Depends(principal), svc: Services = Depends(services)
) -> dict[str, Any]:
    from server.db.models import User

    with svc.db.transaction() as s:
        u = s.get(User, p.user.id)
        assert u is not None
        u.name = body.name.strip()
        return user_out(u)


@router.post("/auth/password")
def change_password(
    body: PasswordIn, p: Principal = Depends(principal), svc: Services = Depends(services)
) -> dict[str, Any]:
    from server.db.models import User

    with svc.db.transaction() as s:
        u = s.get(User, p.user.id)
        assert u is not None
        svc.auth.change_password(s, u, body.current_password, body.new_password, p.session_token)
    return {"ok": True}


@router.get("/invites/{token}")
def get_invite(token: str, svc: Services = Depends(services)) -> dict[str, Any]:
    from server.db.models import Workspace

    with svc.db.transaction() as s:
        inv = svc.auth.get_invite(s, token)
        ws = s.get(Workspace, inv.workspace_id)
        return {
            "email": inv.email,
            "role": inv.role,
            "kind": inv.kind,
            "workspace": ws.name if ws else "",
            "expires_at": inv.expires_at,
        }


@router.post("/invites/{token}/accept")
def accept_invite(
    token: str,
    body: AcceptIn,
    request: Request,
    response: Response,
    svc: Services = Depends(services),
) -> dict[str, Any]:
    from sqlalchemy import select

    from server.db.models import User
    from server.services.licensing import require_feature, seat_count

    with svc.db.transaction() as s:
        inv = svc.auth.get_invite(s, token)
        exists = s.scalars(select(User).where(User.email == inv.email)).first()
        if inv.kind == "invite" and exists is None:
            require_feature(svc, s, "users", current=seat_count(s))
        user = svc.auth.accept_invite(s, token, name=body.name, password=body.password)
    with svc.db.transaction() as s:
        issued = svc.auth.login(
            s,
            user.email,
            body.password,
            ip=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    _set_cookie(response, svc, issued.token)
    return {"ok": True, "user": user_out(user)}
