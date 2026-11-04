"""Identity: passwords, sessions, API keys, invitations, first-run setup.

* Passwords: scrypt (stdlib), per-user salt, constant-time verify.
* Sessions: random 256-bit token in an HttpOnly cookie; only its SHA-256
  is stored, so a database leak does not leak live sessions.
* API keys: ``prism_<prefix>_<secret>``; shown once, stored hashed.
* Invites / password resets: single-use links, hashed, expiring — no
  SMTP server required; an admin copies the link to the person.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as DBSession

from core.clock import utcnow
from server.db.models import (
    ApiKey,
    Invite,
    Membership,
    Role,
    Session,
    User,
    Workspace,
)
from server.errors import BadRequest, Conflict, NotFound, TooManyRequests, Unauthorized
from server.services import audit
from server.services.context import Actor

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1
MIN_PASSWORD = 10
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        # Burn comparable time so absent accounts are not distinguishable.
        hashlib.scrypt(b"x", salt=b"0" * 16, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
        return False
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(digest) // 2,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk.hex(), digest)


def check_password_policy(password: str, email: str = "") -> None:
    if len(password) < MIN_PASSWORD:
        raise BadRequest(f"Password must be at least {MIN_PASSWORD} characters")
    if len(password) > 256:
        raise BadRequest("Password is too long")
    if email and password.lower() == email.lower():
        raise BadRequest("Password must not equal your email address")
    if len(set(password)) < 4:
        raise BadRequest("Password is too simple")


def normalize_email(email: str) -> str:
    e = email.strip().lower()
    if not _EMAIL.match(e) or len(e) > 320:
        raise BadRequest("Enter a valid email address")
    return e


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:60] or "workspace"


class LoginLimiter:
    """Sliding-window failed-login limiter, per client IP and per account."""

    def __init__(self, limit: int, window_s: int = 900) -> None:
        self.limit = limit
        self.window = window_s
        self._fails: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._fails[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def check(self, *keys: str) -> None:
        now = time.monotonic()
        with self._lock:
            for k in keys:
                if len(self._prune(k, now)) >= self.limit:
                    raise TooManyRequests("Too many failed sign-in attempts; try again later")

    def fail(self, *keys: str) -> None:
        now = time.monotonic()
        with self._lock:
            for k in keys:
                self._prune(k, now).append(now)

    def reset(self, *keys: str) -> None:
        with self._lock:
            for k in keys:
                self._fails.pop(k, None)


@dataclass(frozen=True)
class IssuedSession:
    token: str
    session: Session


@dataclass(frozen=True)
class IssuedSecret:
    """A plaintext secret shown to the user exactly once."""

    secret: str
    record_id: str


class AuthService:
    def __init__(self, session_hours: int, login_limit: int) -> None:
        self.session_hours = session_hours
        self.limiter = LoginLimiter(login_limit)

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    @staticmethod
    def needs_setup(s: DBSession) -> bool:
        return (s.scalar(select(func.count()).select_from(User)) or 0) == 0

    def setup(
        self, s: DBSession, *, email: str, name: str, password: str, workspace_name: str
    ) -> tuple[User, Workspace]:
        if not self.needs_setup(s):
            raise Conflict("This instance is already set up")
        email = normalize_email(email)
        check_password_policy(password, email)
        user = User(
            email=email,
            name=name.strip() or email,
            password_hash=hash_password(password),
            is_superadmin=True,
        )
        ws = Workspace(name=workspace_name.strip() or "My workspace", slug=slugify(workspace_name))
        s.add_all([user, ws])
        s.flush()
        s.add(Membership(user_id=user.id, workspace_id=ws.id, role=Role.ADMIN.value))
        s.flush()
        actor = Actor(user.id, user.email, ws.id, Role.ADMIN)
        audit.record(
            s,
            actor,
            "instance.setup",
            target_type="workspace",
            target_id=ws.id,
            description=f"Instance set up by {email}",
        )
        return user, ws

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def login(
        self, s: DBSession, email: str, password: str, *, ip: str | None, user_agent: str | None
    ) -> IssuedSession:
        key_ip, key_acct = f"ip:{ip}", f"acct:{email.strip().lower()}"
        self.limiter.check(key_ip, key_acct)
        user = s.scalars(select(User).where(User.email == email.strip().lower())).first()
        if not verify_password(password, user.password_hash if user else None) or not (
            user and user.is_active
        ):
            self.limiter.fail(key_ip, key_acct)
            audit.record(
                s,
                None,
                "auth.login_failed",
                target_type="user",
                target_id=user.id if user else None,
                description=f"Failed sign-in for {email.strip().lower()[:200]}",
                details={"ip": ip},
            )
            raise Unauthorized("Incorrect email or password")
        self.limiter.reset(key_acct)
        token = secrets.token_urlsafe(32)
        sess = Session(
            id=sha256(token),
            user_id=user.id,
            expires_at=utcnow() + timedelta(hours=self.session_hours),
            ip=ip,
            user_agent=(user_agent or "")[:400],
        )
        user.last_login_at = utcnow()
        s.add(sess)
        s.flush()
        audit.record(
            s,
            None,
            "auth.login",
            target_type="user",
            target_id=user.id,
            description=f"{user.email} signed in",
            details={"ip": ip},
        )
        return IssuedSession(token=token, session=sess)

    @staticmethod
    def resolve_session(s: DBSession, token: str) -> User | None:
        sess = s.get(Session, sha256(token))
        if sess is None or sess.expires_at <= utcnow():
            return None
        user = s.get(User, sess.user_id)
        if user is None or not user.is_active:
            return None
        return user

    @staticmethod
    def logout(s: DBSession, token: str) -> None:
        s.execute(delete(Session).where(Session.id == sha256(token)))

    @staticmethod
    def revoke_all_sessions(s: DBSession, user_id: str) -> None:
        s.execute(delete(Session).where(Session.user_id == user_id))

    @staticmethod
    def purge_expired(s: DBSession) -> int:
        res = s.execute(delete(Session).where(Session.expires_at <= utcnow()))
        return int(res.rowcount or 0)  # type: ignore[attr-defined]

    def change_password(
        self, s: DBSession, user: User, current: str, new: str, keep_token: str | None
    ) -> None:
        if not verify_password(current, user.password_hash):
            raise BadRequest("Current password is incorrect")
        check_password_policy(new, user.email)
        user.password_hash = hash_password(new)
        q = delete(Session).where(Session.user_id == user.id)
        if keep_token:
            q = q.where(Session.id != sha256(keep_token))
        s.execute(q)
        audit.record(
            s,
            None,
            "auth.password_changed",
            target_type="user",
            target_id=user.id,
            description=f"{user.email} changed their password",
        )

    # ------------------------------------------------------------------
    # API keys
    # ------------------------------------------------------------------

    @staticmethod
    def create_api_key(s: DBSession, actor: Actor, name: str) -> IssuedSecret:
        if not actor.user_id:
            raise BadRequest("API keys belong to users")
        prefix = secrets.token_hex(4)
        secret = f"prism_{prefix}_{secrets.token_urlsafe(32)}"
        key = ApiKey(
            user_id=actor.user_id,
            workspace_id=actor.workspace_id,
            name=name.strip()[:200] or "API key",
            prefix=prefix,
            key_hash=sha256(secret),
        )
        s.add(key)
        s.flush()
        audit.record(
            s,
            actor,
            "apikey.create",
            target_type="api_key",
            target_id=key.id,
            description=f"Created API key '{key.name}'",
        )
        return IssuedSecret(secret=secret, record_id=key.id)

    @staticmethod
    def resolve_api_key(s: DBSession, secret: str) -> ApiKey | None:
        if not secret.startswith("prism_"):
            return None
        key = s.scalars(select(ApiKey).where(ApiKey.key_hash == sha256(secret))).first()
        if key is None or key.revoked_at is not None:
            return None
        key.last_used_at = utcnow()
        return key

    @staticmethod
    def revoke_api_key(s: DBSession, actor: Actor, key_id: str) -> None:
        key = s.get(ApiKey, key_id)
        if key is None or key.workspace_id != actor.workspace_id:
            raise NotFound("API key not found")
        if key.user_id != actor.user_id:
            actor.require("admin")
        key.revoked_at = utcnow()
        audit.record(
            s,
            actor,
            "apikey.revoke",
            target_type="api_key",
            target_id=key.id,
            description=f"Revoked API key '{key.name}'",
        )

    # ------------------------------------------------------------------
    # Invites and password resets
    # ------------------------------------------------------------------

    @staticmethod
    def create_invite(
        s: DBSession,
        actor: Actor,
        email: str,
        role: Role,
        *,
        kind: str = "invite",
        hours: int = 72,
    ) -> IssuedSecret:
        actor.require("admin")
        email = normalize_email(email)
        if kind == "invite":
            existing = s.scalars(select(User).where(User.email == email)).first()
            if existing and any(m.workspace_id == actor.workspace_id for m in existing.memberships):
                raise Conflict(f"{email} is already a member of this workspace")
        token = secrets.token_urlsafe(32)
        inv = Invite(
            token_hash=sha256(token),
            workspace_id=actor.workspace_id,
            email=email,
            role=role.value,
            created_by=actor.user_id,
            expires_at=utcnow() + timedelta(hours=hours),
            kind=kind,
        )
        s.add(inv)
        s.flush()
        audit.record(
            s,
            actor,
            f"{kind}.create",
            target_type="invite",
            target_id=inv.id,
            description=f"{'Invited' if kind == 'invite' else 'Reset link for'} {email}"
            + (f" as {role.value}" if kind == "invite" else ""),
        )
        return IssuedSecret(secret=token, record_id=inv.id)

    @staticmethod
    def get_invite(s: DBSession, token: str) -> Invite:
        inv = s.scalars(select(Invite).where(Invite.token_hash == sha256(token))).first()
        if inv is None or inv.accepted_at is not None or inv.expires_at <= utcnow():
            raise NotFound("This link is invalid or has expired")
        return inv

    def accept_invite(self, s: DBSession, token: str, *, name: str, password: str) -> User:
        inv = self.get_invite(s, token)
        check_password_policy(password, inv.email)
        user = s.scalars(select(User).where(User.email == inv.email)).first()
        if inv.kind == "reset":
            if user is None:
                raise NotFound("Account not found")
            user.password_hash = hash_password(password)
            self.revoke_all_sessions(s, user.id)
        else:
            if user is None:
                user = User(
                    email=inv.email,
                    name=name.strip() or inv.email,
                    password_hash=hash_password(password),
                )
                s.add(user)
                s.flush()
            elif not user.password_hash:
                user.password_hash = hash_password(password)
            already = s.scalars(
                select(Membership).where(
                    Membership.user_id == user.id, Membership.workspace_id == inv.workspace_id
                )
            ).first()
            if already is None:
                s.add(Membership(user_id=user.id, workspace_id=inv.workspace_id, role=inv.role))
        inv.accepted_at = utcnow()
        s.flush()
        actor = Actor(user.id, user.email, inv.workspace_id, Role(inv.role))
        what = "invitation" if inv.kind == "invite" else "password reset"
        audit.record(
            s,
            actor,
            f"{inv.kind}.accept",
            target_type="user",
            target_id=user.id,
            description=f"{user.email} accepted {what}",
        )
        return user
