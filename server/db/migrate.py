"""Programmatic Alembic entry points (used by the CLI and on startup)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from server.db.session import Database

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def alembic_config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def upgrade(db: Database, revision: str = "head") -> None:
    """Bring the schema to ``revision`` (idempotent)."""
    cfg = alembic_config(db.url)
    with db.engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, revision)


def current_revision(db: Database) -> str | None:
    with db.engine.connect() as conn:
        if not inspect(conn).has_table("alembic_version"):
            return None
        row = conn.exec_driver_sql("SELECT version_num FROM alembic_version").first()
        return row[0] if row else None


def make_revision(url: str, message: str) -> None:
    """Developer helper: autogenerate a new migration."""
    command.revision(alembic_config(url), message=message, autogenerate=True)
