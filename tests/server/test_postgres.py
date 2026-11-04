"""PostgreSQL compatibility (runs only when PRISM_TEST_DATABASE_URL is set).

    PRISM_TEST_DATABASE_URL=postgresql+psycopg://user:pw@host:5432/db pytest tests/server/test_postgres.py

The target database is wiped (schema ``public`` dropped) at the start.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from server.app import create_app
from server.backup import create_backup, restore_backup
from server.config import Settings
from server.db import Database
from tests.server.test_api import CHART, PASSWORD, H, import_sales, setup_admin
from tests.server.test_licensing import PUB, key

URL = os.environ.get("PRISM_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="PRISM_TEST_DATABASE_URL not set")


def _wipe(url: str) -> None:
    eng = create_engine(url)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    eng.dispose()


def _settings(path: Path, url: str | None) -> Settings:
    return Settings(env="test", data_dir=path, secret_key="k" * 32, base_url="http://testserver",
                    database_url=url, license_public_key=PUB, license_key=key("business"))


def test_full_pipeline_and_cross_database_restore(tmp_path: Path) -> None:
    assert URL
    _wipe(URL)
    pg = _settings(tmp_path / "pg", URL)
    with TestClient(create_app(pg)) as c:
        setup_admin(c)
        ds = import_sales(c)
        chart = c.post("/api/v1/charts", json={"dataset_id": ds["id"], "name": "R", **CHART}, headers=H).json()
        assert c.get(f"/api/v1/charts/{chart['id']}/render").status_code == 200
        assert c.get("/api/v1/audit/verify").json()["ok"] is True

    # SQLite instance -> backup -> restore onto PostgreSQL
    lite = _settings(tmp_path / "lite", None)
    with TestClient(create_app(lite)) as c:
        setup_admin(c)
        import_sales(c)
    archive = create_backup(lite, Database(lite.resolved_database_url))
    pg2 = _settings(tmp_path / "pg2", URL)
    restore_backup(pg2, Database(URL), archive, force=True)
    with TestClient(create_app(pg2)) as c:
        r = c.post("/api/v1/auth/login", json={"email": "admin@acme.test", "password": PASSWORD}, headers=H)
        assert r.status_code == 200
        assert len(c.get("/api/v1/datasets").json()) == 1
        assert c.get("/api/v1/audit/verify").json()["ok"] is True
        # The audit sequence continues after restore (no PK collision).
        assert c.post("/api/v1/datasets/sample", headers=H).status_code == 201
