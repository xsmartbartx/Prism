"""Request dependencies: services, authentication and actor resolution."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from sqlalchemy import select

from server.container import Services
from server.db.models import Membership, Role, User, Workspace
from server.errors import Forbidden, Unauthorized
from server.services.context import Actor

SESSION_COOKIE = "prism_session"
WORKSPACE_HEADER = "x-prism-workspace"


def services(request: Request) -> Services:
    svc: Services = request.app.state.services
    return svc


def client_ip(request: Request) -> str | None:
    """The caller's address, for rate limiting and the audit log.

    Behind the bundled reverse proxy uvicorn's proxy headers rewrite request.client from
    X-Forwarded-For (PRISM_FORWARDED_ALLOW_IPS). Behind a CDN that proxy only sees the CDN's
    edge, so a deployment that is reachable *only* through it can name the CDN's client-IP
    header (PRISM_CLIENT_IP_HEADER, e.g. CF-Connecting-IP) instead.
    """
    header = services(request).settings.client_ip_header
    if header:
        value = request.headers.get(header, "").strip()
        if value and len(value) <= 64 and all(c in "0123456789abcdefABCDEF.:" for c in value):
            return value
    return request.client.host if request.client else None


@dataclass(frozen=True)
class Principal:
    """The authenticated user plus the workspace actor they act as."""

    user: User
    actor: Actor
    session_token: str | None
    memberships: list[tuple[Workspace, Role]]


def _resolve(request: Request, *, required: bool) -> Principal | None:
    svc = services(request)
    token = request.cookies.get(SESSION_COOKIE)
    auth = request.headers.get("authorization", "")
    with svc.db.transaction() as s:
        user: User | None = None
        via = "session"
        key_workspace: str | None = None
        if auth.lower().startswith("bearer "):
            key = svc.auth.resolve_api_key(s, auth[7:].strip())
            if key is None:
                raise Unauthorized("Invalid or revoked API key")
            from server.services.licensing import require_feature

            require_feature(svc, s, "api")
            user = s.get(User, key.user_id)
            via, key_workspace, token = "api_key", key.workspace_id, None
        elif token:
            user = svc.auth.resolve_session(s, token)
        if user is None or not user.is_active:
            if required:
                raise Unauthorized("Sign in required")
            return None
        rows = s.execute(
            select(Workspace, Membership.role)
            .join(Membership, Membership.workspace_id == Workspace.id)
            .where(Membership.user_id == user.id)
            .order_by(Workspace.created_at)
        ).all()
        memberships = [(ws, Role(role)) for ws, role in rows]
        if not memberships:
            raise Forbidden("Your account is not a member of any workspace")
        wanted = key_workspace or request.headers.get(WORKSPACE_HEADER)
        chosen = next((m for m in memberships if m[0].id == wanted), None)
        if wanted and chosen is None:
            raise Forbidden("You are not a member of that workspace")
        ws, role = chosen or memberships[0]
    actor = Actor(
        user_id=user.id,
        label=user.email,
        workspace_id=ws.id,
        role=role,
        ip=client_ip(request),
        via=via,
    )
    request.state.user = user.email
    return Principal(user=user, actor=actor, session_token=token, memberships=memberships)


def principal(request: Request) -> Principal:
    p = _resolve(request, required=True)
    assert p is not None
    return p


def optional_principal(request: Request) -> Principal | None:
    return _resolve(request, required=False)


def actor(request: Request) -> Actor:
    return principal(request).actor
