"""Shared fixtures for server-layer tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from data.load.store import DatasetStore
from server.config import Settings
from server.db import Database
from server.db.models import Membership, Role, User, Workspace
from server.services.context import Actor


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings(env="test", data_dir=tmp_path / "var", secret_key="test-secret-key")
    s.ensure_dirs()
    return s


@pytest.fixture
def db(settings: Settings) -> Iterator[Database]:
    database = Database(settings.resolved_database_url)
    database.create_all()
    yield database
    database.dispose()


@pytest.fixture
def store(settings: Settings) -> DatasetStore:
    return DatasetStore(settings.datasets_dir)


@pytest.fixture
def session(db: Database) -> Iterator[Session]:
    s = db.session()
    yield s
    s.rollback()
    s.close()


def make_actor(s: Session, role: Role = Role.ADMIN, email: str = "owner@example.com") -> Actor:
    ws = s.query(Workspace).first()
    if ws is None:
        ws = Workspace(name="Acme", slug="acme")
        s.add(ws)
        s.flush()
    user = User(email=email, name=email.split("@")[0])
    s.add(user)
    s.flush()
    s.add(Membership(user_id=user.id, workspace_id=ws.id, role=role.value))
    s.flush()
    return Actor(user_id=user.id, label=user.email, workspace_id=ws.id, role=role)


@pytest.fixture
def actor(session: Session) -> Actor:
    return make_actor(session)
