"""Tests for the SQLite and Parquet connectors."""

from __future__ import annotations

import io
import sqlite3
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from core.errors import ConnectorError
from data.connectors import (
    ConnectorLimits,
    is_parquet,
    is_sqlite,
    list_tables,
    read_parquet,
    read_table,
)
from data.connectors.sqlite import _Database


def _sqlite(tmp_path: Path, script: str, *, wal: bool = False) -> bytes:
    path = tmp_path / "source.db"
    conn = sqlite3.connect(path)
    if wal:
        conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(script)
    conn.commit()
    if wal:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    return path.read_bytes()


SHOP = """
CREATE TABLE orders (id INTEGER PRIMARY KEY AUTOINCREMENT, region TEXT, placed TEXT,
                     total REAL, paid INTEGER, receipt BLOB);
INSERT INTO orders (region, placed, total, paid, receipt) VALUES
  ('EU', '2026-01-05', 120.5, 1, x'00ff'),
  ('US', '2026-01-06', 80, 0, NULL),
  (NULL, '2026-01-07', 99.99, 1, NULL);
CREATE TABLE "we""ird name" (k TEXT, v INTEGER);
INSERT INTO "we""ird name" VALUES ('a', 1), ('b', 2);
CREATE VIEW big_orders AS SELECT * FROM orders WHERE total > 100;
"""


class TestSqlite:
    def test_lists_only_ordinary_tables(self, tmp_path: Path) -> None:
        raw = _sqlite(tmp_path, SHOP + "CREATE VIRTUAL TABLE notes USING fts5(body);")
        assert is_sqlite(raw)
        names = [t["name"] for t in list_tables(raw)]
        # No view, no virtual table, no sqlite_sequence (from AUTOINCREMENT); fts5 shadow
        # tables are ordinary tables and stay listed.
        assert names[:2] == ["orders", 'we"ird name']
        assert "big_orders" not in names
        assert "notes" not in names
        assert not any(n.startswith("sqlite_") for n in names)

    def test_reads_first_table_as_text_rows(self, tmp_path: Path) -> None:
        table = read_table(_sqlite(tmp_path, SHOP))
        assert table.sheet == "orders"
        assert table.rows[0] == ["id", "region", "placed", "total", "paid", "receipt"]
        assert table.rows[1] == ["1", "EU", "2026-01-05", "120.5", "1", ""]
        assert table.rows[2] == ["2", "US", "2026-01-06", "80", "0", ""]
        assert table.rows[3][1] == ""
        assert not table.truncated
        assert any("BLOB" in w and "receipt" in w for w in table.warnings)

    def test_reads_named_table_with_quotes(self, tmp_path: Path) -> None:
        table = read_table(_sqlite(tmp_path, SHOP), 'we"ird name')
        assert table.rows == [["k", "v"], ["a", "1"], ["b", "2"]]

    def test_generated_columns_read_under_hardened_schema(self, tmp_path: Path) -> None:
        raw = _sqlite(
            tmp_path,
            "CREATE TABLE p (name TEXT, code TEXT GENERATED ALWAYS AS (upper(substr(name, 1, 3))));"
            "INSERT INTO p (name) VALUES ('widget');",
        )
        assert read_table(raw).rows == [["name", "code"], ["widget", "WID"]]

    def test_refuses_views_and_unknown_tables(self, tmp_path: Path) -> None:
        raw = _sqlite(tmp_path, SHOP)
        for name in ("big_orders", "missing", "sqlite_sequence"):
            with pytest.raises(ConnectorError, match="not found"):
                read_table(raw, name)

    def test_truncates_at_max_rows(self, tmp_path: Path) -> None:
        table = read_table(_sqlite(tmp_path, SHOP), max_rows=2)
        assert table.truncated
        assert len(table.rows) == 3  # header + 2

    def test_column_cap(self, tmp_path: Path) -> None:
        table = read_table(_sqlite(tmp_path, SHOP), limits=ConnectorLimits(max_columns=2))
        assert table.rows[0] == ["id", "region"]
        assert all(len(r) <= 2 for r in table.rows)
        assert any("first 2 of 6" in w for w in table.warnings)

    def test_wal_database_is_readable(self, tmp_path: Path) -> None:
        raw = _sqlite(tmp_path, SHOP, wal=True)
        assert raw[18] == 2
        table = read_table(raw)
        assert len(table.rows) == 4
        assert any("write-ahead" in w for w in table.warnings)

    def test_rejects_non_databases(self, tmp_path: Path) -> None:
        assert not is_sqlite(b"PK\x03\x04")
        with pytest.raises(ConnectorError, match="Not a SQLite"):
            list_tables(b"id,name\n1,a\n")
        with pytest.raises(ConnectorError):
            list_tables(b"SQLite format 3\x00" + b"\x00" * 600)

    def test_empty_database(self, tmp_path: Path) -> None:
        raw = _sqlite(tmp_path, "CREATE VIEW v AS SELECT 1;")
        assert list_tables(raw) == []
        with pytest.raises(ConnectorError, match="no tables"):
            read_table(raw)

    def test_long_reads_are_stopped(self, tmp_path: Path) -> None:
        raw = _sqlite(
            tmp_path,
            "CREATE TABLE n (i INTEGER);"
            "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 50000)"
            " INSERT INTO n SELECT x FROM c;",
        )
        with pytest.raises(ConnectorError, match="longer than"):
            read_table(raw, timeout_s=0.0)

    def test_only_reads_are_authorised(self, tmp_path: Path) -> None:
        db = _Database(_sqlite(tmp_path, SHOP), ConnectorLimits(), 60.0)
        try:
            for sql in (
                "DELETE FROM orders",
                "ATTACH DATABASE ':memory:' AS other",
                "PRAGMA query_only = OFF",
                "SELECT * FROM big_orders",
            ):
                with pytest.raises(ConnectorError):
                    db.run(sql).fetchall()
            assert db.run("SELECT count(*) FROM orders").fetchone() == (3,)
        finally:
            db.close()


def _parquet(table: pa.Table) -> bytes:
    buf = io.BytesIO()
    pq.write_table(table, buf)
    return buf.getvalue()


class TestParquet:
    def test_reads_typed_columns_as_text(self) -> None:
        raw = _parquet(
            pa.table(
                {
                    "id": pa.array([1, 2, None], pa.int64()),
                    "price": pa.array([Decimal("9.50"), Decimal("12.00"), None], pa.decimal128(6, 2)),
                    "day": pa.array([date(2026, 1, 5), date(2026, 1, 6), None]),
                    "ok": pa.array([True, False, None]),
                    "name": pa.array(["a", "b", None]),
                }
            )
        )
        assert is_parquet(raw)
        table = read_parquet(raw)
        assert table.rows[0] == ["id", "price", "day", "ok", "name"]
        assert table.rows[1] == ["1", "9.50", "2026-01-05", "true", "a"]
        assert table.rows[3] == ["", "", "", "", ""]
        assert table.warnings == []

    def test_awkward_types_are_reported(self) -> None:
        raw = _parquet(
            pa.table(
                {
                    "at": pa.array(
                        [datetime(2026, 1, 5, 12, 0, tzinfo=UTC)], pa.timestamp("us", tz="UTC")
                    ),
                    "tags": pa.array([["x", "y"]]),
                    "blob": pa.array([b"\x00\x01"], pa.binary()),
                }
            )
        )
        table = read_parquet(raw)
        assert table.rows[1] == ["2026-01-05 12:00:00", '["x", "y"]', ""]
        text = " ".join(table.warnings)
        assert "UTC: at" in text and "JSON text: tags" in text and "empty in: blob" in text

    def test_truncates_and_caps_columns(self) -> None:
        raw = _parquet(pa.table({"a": list(range(25_000)), "b": list(range(25_000))}))
        table = read_parquet(raw, max_rows=12_000, limits=ConnectorLimits(max_columns=1))
        assert table.truncated
        assert len(table.rows) == 12_001
        assert table.rows[0] == ["a"] and table.rows[-1] == ["11999"]
        assert any("first 1 of 2" in w for w in table.warnings)

    def test_rejects_non_parquet(self) -> None:
        assert not is_parquet(b"PAR1")
        with pytest.raises(ConnectorError, match="Not a Parquet"):
            read_parquet(b"id,name\n1,a\n")
        with pytest.raises(ConnectorError, match="Unable to read"):
            read_parquet(b"PAR1" + b"\x00" * 64 + b"PAR1")
