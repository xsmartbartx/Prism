"""Request-scoped actor context passed into every service call."""

from __future__ import annotations

from dataclasses import dataclass

from server.db.models import Role
from server.errors import Forbidden

# Capability -> roles allowed. Auditor deliberately cannot read data rows.
_CAPABILITIES: dict[str, frozenset[Role]] = {
    "read": frozenset({Role.VIEWER, Role.EXPLORER, Role.AUTHOR, Role.STEWARD, Role.ADMIN}),
    "explore": frozenset({Role.EXPLORER, Role.AUTHOR, Role.STEWARD, Role.ADMIN}),
    "author": frozenset({Role.AUTHOR, Role.STEWARD, Role.ADMIN}),
    "steward": frozenset({Role.STEWARD, Role.ADMIN}),
    "admin": frozenset({Role.ADMIN}),
    "audit": frozenset({Role.AUDITOR, Role.ADMIN}),
}


@dataclass(frozen=True)
class Actor:
    """Who is acting, in which workspace, with which role."""

    user_id: str | None
    label: str
    workspace_id: str
    role: Role
    ip: str | None = None
    via: str = "session"  # session | api_key | share | system

    def can(self, capability: str) -> bool:
        return self.role in _CAPABILITIES[capability]

    def require(self, capability: str) -> None:
        if not self.can(capability):
            raise Forbidden(f"Your role ({self.role.value}) does not allow '{capability}'")
