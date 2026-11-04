"""Tests for the metadata store and migrations."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from sqlalchemy import inspect, select

from core.clock import utcnow
from server.db import Database
from server.db.migrate import current_revision, upgrade
from server.db.models import Base, Session, User


def test_migrations_match_models(tmp_path: Path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'm.db'}")
    upgrade(db)
    upgrade(db)  # idempotent
    assert current_revision(db) is not None
    tables = set(inspect(db.engine).get_table_names())
    assert set(Base.metadata.tables) <= tables


def test_datetimes_are_utc_aware() -> None:
    db = Database("sqlite://")
    db.create_all()
    with db.transaction() as s:
        u = User(email="a@example.com", name="A")
        s.add(u)
        s.flush()
        s.add(Session(id="x" * 64, user_id=u.id, expires_at=utcnow() + timedelta(hours=1)))
    with db.transaction() as s:
        sess = s.scalars(select(Session)).one()
        assert sess.expires_at.tzinfo is not None
        assert sess.expires_at > utcnow()


def test_transaction_rolls_back_on_error() -> None:
    db = Database("sqlite://")
    db.create_all()
    try:
        with db.transaction() as s:
            s.add(User(email="b@example.com", name="B"))
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    with db.transaction() as s:
        assert s.scalars(select(User)).first() is None
