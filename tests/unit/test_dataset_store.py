"""Tests for the Parquet dataset store."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pyarrow as pa
import pytest

from data.load.store import DatasetStore, arrow_schema


def _table() -> pa.Table:
    schema = arrow_schema([("region", "string"), ("amount", "float"), ("day", "date")])
    return pa.Table.from_pylist(
        [
            {"region": "EU", "amount": 1.5, "day": date(2026, 1, 1)},
            {"region": "US", "amount": None, "day": date(2026, 1, 2)},
        ],
        schema=schema,
    )


def test_write_and_read_roundtrip(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path)
    stored = store.write(_table(), "ws1", "ds1", 1)
    assert stored.row_count == 2
    assert len(stored.content_hash) == 64
    assert stored.path.name == "v1.parquet"
    back = store.read(stored.path)
    assert back.to_pylist()[0]["region"] == "EU"
    assert back.schema.field("day").type == pa.date32()


def test_versions_are_immutable(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path)
    store.write(_table(), "ws1", "ds1", 1)
    with pytest.raises(FileExistsError):
        store.write(_table(), "ws1", "ds1", 1)


def test_content_hash_is_deterministic(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path)
    a = store.write(_table(), "ws1", "ds1", 1)
    b = store.write(_table(), "ws1", "ds1", 2)
    assert a.content_hash == b.content_hash


def test_rejects_path_traversal(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path / "store")
    with pytest.raises(ValueError):
        store.version_path("../etc", "ds1", 1)
    outside = tmp_path / "x.parquet"
    outside.write_bytes(b"")
    with pytest.raises(ValueError):
        store.read(outside)


def test_quarantine_path_and_delete(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path)
    q = store.write(_table(), "ws1", "ds1", 1, quarantine=True)
    assert q.path.name == "v1.quarantine.parquet"
    assert store.usage_bytes() > 0
    store.delete_dataset("ws1", "ds1")
    assert not q.path.exists()
