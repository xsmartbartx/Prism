"""Sharing service — read-only share tokens for artifacts."""

from __future__ import annotations

import hashlib
import hmac
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from catalog.models import ArtifactType, AuditAction

_SECRET_KEY = b"prism-share-key-v0-dev"


@dataclass(frozen=True)
class ShareToken:
    """A signed, revocable, expiring share token for one artifact."""

    token_id: str
    artifact_id: str
    artifact_type: ArtifactType
    created_by: str | None = field(default=None)
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: datetime | None = field(default=None)
    is_revoked: bool = field(default=False)
    max_uses: int | None = field(default=None)
    use_count: int = field(default=0)
    signature: str = field(default="")

    def is_valid(self, now: datetime | None = None) -> bool:
        t = now or datetime.utcnow()
        if self.is_revoked: return False
        if self.expires_at and t > self.expires_at: return False
        if self.max_uses is not None and self.use_count >= self.max_uses: return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "token_id": self.token_id,
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type.value,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "is_revoked": self.is_revoked,
            "max_uses": self.max_uses,
            "use_count": self.use_count,
        }


def _sign(payload: str, secret: bytes = _SECRET_KEY) -> str:
    return hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()


def _verify(payload: str, sig: str, secret: bytes = _SECRET_KEY) -> bool:
    return hmac.compare_digest(_sign(payload, secret), sig)
class ShareManager:
    """Manages share tokens — create, validate, revoke."""

    def __init__(self, audit_callback: Callable | None = None) -> None:
        self._tokens: dict[str, ShareToken] = {}
        self._audit = audit_callback

    def create_share(
        self,
        artifact_id: str,
        artifact_type: ArtifactType = ArtifactType.CHART,
        *,
        created_by: str | None = None,
        expires_in_hours: int | None = None,
        max_uses: int | None = None,
    ) -> ShareToken:
        if not artifact_id:
            raise ValueError("artifact_id is required")
        token_id = uuid.uuid4().hex[:16]
        now = datetime.utcnow()
        expires_at = now + timedelta(hours=expires_in_hours) if expires_in_hours else None
        payload = f"{token_id}:{artifact_id}:{artifact_type.value}:{now.isoformat()}"
        sig = _sign(payload)
        token = ShareToken(token_id=token_id, artifact_id=artifact_id,
            artifact_type=artifact_type, created_by=created_by,
            created_at=now, expires_at=expires_at, max_uses=max_uses, signature=sig)
        self._tokens[token_id] = token
        self._emit("create", artifact_type, artifact_id, created_by, token_id)
        return token

    def validate_token(self, token_id: str, signature: str | None = None,
                       now: datetime | None = None) -> ShareToken | None:
        token = self._tokens.get(token_id)
        if not token: return None
        if signature:
            payload = f"{token.token_id}:{token.artifact_id}:{token.artifact_type.value}:{token.created_at.isoformat()}"
            if not _verify(payload, signature): return None
        return token if token.is_valid(now) else None

    def use_token(self, token_id: str, now: datetime | None = None) -> bool:
        token = self._tokens.get(token_id)
        if not token or not token.is_valid(now): return False
        updated = ShareToken(token_id=token.token_id, artifact_id=token.artifact_id,
            artifact_type=token.artifact_type, created_by=token.created_by,
            created_at=token.created_at, expires_at=token.expires_at,
            is_revoked=token.is_revoked, max_uses=token.max_uses,
            use_count=token.use_count + 1, signature=token.signature)
        self._tokens[token_id] = updated
        return True

    def revoke_share(self, token_id: str, revoked_by: str | None = None) -> ShareToken | None:
        token = self._tokens.get(token_id)
        if not token: return None
        updated = ShareToken(token_id=token.token_id, artifact_id=token.artifact_id,
            artifact_type=token.artifact_type, created_by=token.created_by,
            created_at=token.created_at, expires_at=token.expires_at,
            is_revoked=True, max_uses=token.max_uses, use_count=token.use_count,
            signature=token.signature)
        self._tokens[token_id] = updated
        self._emit("revoke", token.artifact_type, token.artifact_id, revoked_by, token_id)
        return updated

    def list_shares(self, artifact_id: str) -> list[ShareToken]:
        return [t for t in self._tokens.values() if t.artifact_id == artifact_id]

    def get_token(self, token_id: str) -> ShareToken | None:
        return self._tokens.get(token_id)

    def _emit(self, action: str, t: ArtifactType, tid: str,
              actor: str | None, token_id: str) -> None:
        if self._audit:
            desc = f"Share {action}: token {token_id} for {t.value} {tid}"
            self._audit(AuditAction.SHARE, t, tid, actor, desc)