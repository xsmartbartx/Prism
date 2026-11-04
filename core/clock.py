"""Clock helpers — the platform's single source of "now".

All timestamps are timezone-aware UTC. Routing every call through one
function keeps tests deterministic (monkeypatch ``utcnow``) and stops
naive datetimes leaking into persisted artifacts.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Return the current time as an aware UTC datetime."""
    return datetime.now(UTC)
