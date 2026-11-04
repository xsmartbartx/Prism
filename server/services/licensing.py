"""Plan limits (placeholder; full license verification lands with licensing)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server.db.models import User


def seat_count(s: Session) -> int:
    return int(s.scalar(select(func.count()).select_from(User).where(User.is_active)) or 0)


def require_feature(svc: Any, s: Session, feature: str, *, current: int | None = None) -> None:
    """Raise LimitExceeded when the active plan does not allow ``feature``."""
    return None


def dataset_count(s: Session, workspace_id: str | None = None) -> int:
    from server.db.models import Dataset

    stmt = select(func.count()).select_from(Dataset)
    if workspace_id:
        stmt = stmt.where(Dataset.workspace_id == workspace_id)
    return int(s.scalar(stmt) or 0)


def show_branding(svc: Any, s: Session) -> bool:
    """Public pages show 'Made with Prism' unless the plan allows white-labelling."""
    return True
