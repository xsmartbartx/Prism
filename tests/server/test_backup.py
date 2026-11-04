"""Backup/restore round trip across fresh instances."""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.backup import create_backup, prune_backups, restore_backup
from server.cli import main
from server.config import Settings
from server.db import Database
from tests.server.test_api import CHART, PASSWORD, H, import_sales, setup_admin
from tests.server.test_licensing import PUB, key


def _settings(path: Path) -> Settings:
    return Settings(env="test", data_dir=path, secret_key="k" * 32, base_url="http://testserver",
                    license_public_key=PUB, license_key=key("business"))


def test_roundtrip(tmp_path: Path) -> None:
    src = _settings(tmp_path / "a")
    with TestClient(create_app(src)) as c:
        setup_admin(c)
        ds = import_sales(c)
        chart = c.post("/api/v1/charts", json={"dataset_id": ds["id"], "name": "R", **CHART}, headers=H).json()
        share = c.post("/api/v1/shares", json={"artifact_type": "chart", "artifact_id": chart["id"]}, headers=H).json()
    archive = create_backup(src, Database(src.resolved_database_url), include_uploads=True)
    with tarfile.open(archive) as tar:
        names = tar.getnames()
    assert "manifest.json" in names and "db/datasets.jsonl" in names
    assert any(n.startswith("datasets/") and n.endswith(".parquet") for n in names)

    dst = _settings(tmp_path / "b")
    dst.ensure_dirs()
    manifest = restore_backup(dst, Database(dst.resolved_database_url), archive)
    assert manifest["tables"]["datasets"] == 1
    with TestClient(create_app(dst)) as c:
        r = c.post("/api/v1/auth/login", json={"email": "admin@acme.test", "password": PASSWORD}, headers=H)
        assert r.status_code == 200
        q = c.post(f"/api/v1/datasets/{ds['id']}/query", json=CHART["query"], headers=H)
        assert q.status_code == 200 and q.json()["rows"][0]["Region"] == "APAC"
        assert c.get(f"/s/{share['token']}").status_code == 200
        assert c.get("/api/v1/audit/verify").json()["ok"] is True
        # Restoring over existing data needs --force
        with pytest.raises(RuntimeError):
            restore_backup(dst, Database(dst.resolved_database_url), archive)


def test_prune(tmp_path: Path) -> None:
    for i in range(5):
        (tmp_path / f"prism-backup-2026010{i}T000000Z.tar.gz").write_bytes(b"x")
    gone = prune_backups(tmp_path, 2)
    assert len(gone) == 3 and len(list(tmp_path.iterdir())) == 2


def test_rejects_path_traversal(tmp_path: Path) -> None:
    import io

    evil = tmp_path / "evil.tar.gz"
    with tarfile.open(evil, "w:gz") as tar:
        info = tarfile.TarInfo("../../escape.txt")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    s = _settings(tmp_path / "c")
    with pytest.raises(ValueError, match="Unsafe"):
        restore_backup(s, Database(s.resolved_database_url), evil)


def test_cli_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from server.config import get_settings

    monkeypatch.setenv("PRISM_DATA_DIR", str(tmp_path / "d"))
    get_settings.cache_clear()
    try:
        assert main(["migrate"]) == 0
        assert main(["backup", "--keep", "1"]) == 0
        assert len(list((tmp_path / "d" / "backups").glob("*.tar.gz"))) == 1
    finally:
        get_settings.cache_clear()
