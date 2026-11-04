"""Engine and session lifecycle for the metadata store."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from server.db.models import Base


def _sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


class Database:
    """Owns the SQLAlchemy engine and session factory."""

    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.url = url
        kwargs: dict[str, Any] = {"echo": echo, "future": True, "pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        self.engine: Engine = create_engine(url, **kwargs)
        if url.startswith("sqlite"):
            event.listen(self.engine, "connect", _sqlite_pragmas)
        self._factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def create_all(self) -> None:
        """Create tables directly (tests). Production uses Alembic migrations."""
        Base.metadata.create_all(self.engine)

    def session(self) -> Session:
        return self._factory()

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """Session scoped to one unit of work: commit on success, rollback on error."""
        s = self._factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def dispose(self) -> None:
        self.engine.dispose()
