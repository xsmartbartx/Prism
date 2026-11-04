"""Backup and restore — portable across SQLite and PostgreSQL.

An archive (``prism-backup-<timestamp>.tar.gz``) contains:

* ``manifest.json``  — product version, schema revision, row counts;
* ``db/<table>.jsonl`` — every metadata row, one JSON object per line;
* ``datasets/…``      — the immutable Parquet dataset versions;
* ``uploads/…``       — original uploaded files (optional).

Because the metadata is exported logically rather than as a database
file, a backup taken on SQLite restores onto PostgreSQL and vice versa.
"""

from __future__ import annotations

import io
import json
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.orm import Session

from core.clock import utcnow
from server import __version__
from server.config import Settings
from server.db import Database
from server.db.migrate import current_revision, upgrade
from server.db.models import Base, User, UTCDateTime

FORMAT_VERSION = 1


def _encode(row: dict[str, Any]) -> dict[str, Any]:
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in row.items()}


def _decode(table: Any, row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for col in table.columns:
        if isinstance(col.type, UTCDateTime) and isinstance(out.get(col.name), str):
            out[col.name] = datetime.fromisoformat(out[col.name])
    return out


def _add_bytes(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = int(utcnow().timestamp())
    info.mode = 0o600
    tar.addfile(info, io.BytesIO(data))


def create_backup(
    settings: Settings, db: Database, *, include_uploads: bool = False, out_dir: Path | None = None
) -> Path:
    """Write a consistent backup archive and return its path."""
    out = out_dir or settings.backups_dir
    out.mkdir(parents=True, exist_ok=True)
    stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
    target = out / f"prism-backup-{stamp}.tar.gz"
    tmp = target.with_suffix(".partial")
    counts: dict[str, int] = {}
    with tarfile.open(tmp, "w:gz") as tar:
        # One read transaction for a consistent snapshot of metadata.
        with db.engine.connect() as conn, conn.begin():
            for table in Base.metadata.sorted_tables:
                lines = []
                for row in conn.execute(select(table)).mappings():
                    lines.append(json.dumps(_encode(dict(row)), ensure_ascii=False, default=str))
                counts[table.name] = len(lines)
                _add_bytes(tar, f"db/{table.name}.jsonl", ("\n".join(lines) + "\n").encode())
        # Dataset versions are immutable files: copying after the snapshot is safe.
        if settings.datasets_dir.exists():
            tar.add(settings.datasets_dir, arcname="datasets")
        if include_uploads and settings.uploads_dir.exists():
            tar.add(settings.uploads_dir, arcname="uploads")
        manifest = {
            "format": FORMAT_VERSION,
            "product": "prism",
            "version": __version__,
            "schema_revision": current_revision(db),
            "created_at": utcnow().isoformat(),
            "tables": counts,
            "includes_uploads": include_uploads,
        }
        _add_bytes(tar, "manifest.json", json.dumps(manifest, indent=2).encode())
    tmp.rename(target)
    target.chmod(0o600)
    return target


def prune_backups(directory: Path, keep: int) -> list[Path]:
    """Delete all but the newest ``keep`` archives; return deleted paths."""
    archives = sorted(directory.glob("prism-backup-*.tar.gz"))
    doomed = archives[:-keep] if keep > 0 else []
    for p in doomed:
        p.unlink()
    return doomed


def _safe_members(tar: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = []
    for m in tar.getmembers():
        p = Path(m.name)
        if p.is_absolute() or ".." in p.parts or m.issym() or m.islnk():
            raise ValueError(f"Unsafe path in archive: {m.name}")
        members.append(m)
    return members


def restore_backup(
    settings: Settings, db: Database, archive: Path, *, force: bool = False
) -> dict[str, Any]:
    """Restore an archive into this instance. Refuses a non-empty instance unless ``force``."""
    settings.ensure_dirs()
    upgrade(db)
    with Session(db.engine) as s:
        has_users = (s.scalar(select(func.count()).select_from(User)) or 0) > 0
    if has_users and not force:
        raise RuntimeError("This instance already has data. Use --force to replace it.")

    with tempfile.TemporaryDirectory() as tmpdir, tarfile.open(archive, "r:gz") as tar:
        members = _safe_members(tar)
        tar.extractall(tmpdir, members=members)
        root = Path(tmpdir)
        manifest: dict[str, Any] = json.loads((root / "manifest.json").read_text())
        if manifest.get("product") != "prism" or manifest.get("format") != FORMAT_VERSION:
            raise ValueError("Not a Prism backup archive")
        with db.engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(delete(table))
            for table in Base.metadata.sorted_tables:
                path = root / "db" / f"{table.name}.jsonl"
                if not path.exists():
                    continue
                rows = [
                    _decode(table, json.loads(line))
                    for line in path.read_text().splitlines()
                    if line.strip()
                ]
                if rows:
                    conn.execute(insert(table), rows)
            if conn.dialect.name == "postgresql":
                conn.execute(
                    text(
                        "SELECT setval(pg_get_serial_sequence('audit_events', 'seq'), "
                        "COALESCE((SELECT MAX(seq) FROM audit_events), 1))"
                    )
                )
        for sub, dest in (("datasets", settings.datasets_dir), ("uploads", settings.uploads_dir)):
            src = root / sub
            if src.exists():
                for f in src.rglob("*"):
                    if f.is_file():
                        target = dest / f.relative_to(src)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(f.read_bytes())
        # Stored absolute paths point at the original data dir; rebase them.
        _rebase_paths(db, settings)
    return manifest


def _rebase_paths(db: Database, settings: Settings) -> None:
    from server.db.models import DatasetVersion, Import

    with db.transaction() as s:
        for v in s.scalars(select(DatasetVersion)):
            v.parquet_path = str(_rebase(v.parquet_path, "datasets", settings.datasets_dir))
            if v.quarantine_path:
                v.quarantine_path = str(
                    _rebase(v.quarantine_path, "datasets", settings.datasets_dir)
                )
        for i in s.scalars(select(Import)):
            i.storage_path = str(_rebase(i.storage_path, "uploads", settings.uploads_dir))


def _rebase(path: str, marker: str, new_root: Path) -> Path:
    parts = Path(path).parts
    if marker in parts:
        idx = len(parts) - 1 - parts[::-1].index(marker)
        return new_root.joinpath(*parts[idx + 1 :])
    return Path(path)
