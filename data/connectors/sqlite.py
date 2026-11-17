"""SQLite connector (.sqlite, .sqlite3, .db) — one table at a time, read-only.

An uploaded database is untrusted, so it is never opened as a file on disk:
the bytes are deserialised into a private in-memory connection and read
under these constraints:

  * ``PRAGMA query_only`` — nothing can be written, not even to the copy;
  * ``PRAGMA trusted_schema = OFF`` — functions named in the file's own
    schema (generated columns, defaults) are limited to harmless built-ins;
  * ``PRAGMA cell_size_check = ON`` — extra checks against malformed pages;
  * only ordinary tables are offered: no views (they can run arbitrary,
    expensive SQL), no virtual tables (they call into extension modules),
    no ``sqlite_`` internal tables;
  * an authorizer allows only reads, and none made through a view or a
    trigger from the file; a progress handler stops any statement that runs
    longer than ``timeout_s``;
  * extension loading stays disabled (Python's default).

Values become the same canonical text as spreadsheet cells, so typing
happens once, later, against the column contract. The first row returned
is the table's column names.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any

from core.errors import ConnectorError
from data.connectors.base import ConnectorLimits, SourceTable
from data.connectors.spreadsheet import cell_to_text

SQLITE_MAGIC = b"SQLite format 3\x00"
DEFAULT_TIMEOUT_S = 120.0  # per read; includes converting rows to text

_ALLOWED_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
_ALLOWED_PRAGMAS = {"table_info", "table_xinfo"}


def is_sqlite(raw: bytes) -> bool:
    return raw.startswith(SQLITE_MAGIC)


def _authorizer(
    action: int, arg1: str | None, _arg2: str | None, _db: str | None, via: str | None
) -> int:
    if via is not None:  # reached through a view or trigger defined in the uploaded file
        return sqlite3.SQLITE_DENY
    if action in _ALLOWED_ACTIONS:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and (arg1 or "").lower() in _ALLOWED_PRAGMAS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


class _Database:
    """A hardened, read-only, in-memory view of an uploaded database."""

    def __init__(self, raw: bytes, limits: ConnectorLimits, timeout_s: float) -> None:
        if not is_sqlite(raw):
            raise ConnectorError("Not a SQLite database (missing 'SQLite format 3' header)")
        if len(raw) < 512:
            raise ConnectorError("SQLite database is truncated")
        self.warnings: list[str] = []
        image: bytes | bytearray = raw
        # Bytes 18-19 are the read/write format versions: 2 means WAL. An in-memory copy cannot
        # use a WAL file, so read it as a rollback-journal database. Anything still in a -wal
        # file next to the original was never uploaded. Copy only then: SQLite takes its own
        # copy of the image anyway, and uploads can be large.
        if raw[18] == 2 or raw[19] == 2:
            image = bytearray(raw)
            image[18] = image[19] = 1
            self.warnings.append(
                "This database uses write-ahead logging; changes not yet checkpointed into the "
                "main file (a separate -wal file) are not included"
            )
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            self.conn.deserialize(image)
            for pragma in ("query_only = ON", "trusted_schema = OFF", "cell_size_check = ON"):
                self.conn.execute(f"PRAGMA {pragma}")
            # Schema of the uploaded file: read before the authorizer narrows what may run.
            self.tables = self._ordinary_tables()
        except sqlite3.DatabaseError as exc:
            self.conn.close()
            raise ConnectorError(f"Unable to read SQLite database: {exc}") from exc
        self.conn.set_authorizer(_authorizer)
        self._deadline = 0.0
        self._timeout_s = timeout_s
        self.conn.set_progress_handler(self._over_time, 10_000)
        self.limits = limits

    def _over_time(self) -> int:
        return 1 if self._deadline and time.monotonic() > self._deadline else 0

    def _ordinary_tables(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT name, sql FROM sqlite_schema WHERE type = 'table' ORDER BY rowid"
        ).fetchall()
        out = []
        for name, sql in rows:
            if not isinstance(name, str) or name.lower().startswith("sqlite_"):
                continue
            if (sql or "").lstrip().upper().startswith("CREATE VIRTUAL"):
                continue
            out.append(name)
        return out

    def error(self, exc: sqlite3.DatabaseError) -> ConnectorError:
        """The connector error for a failed statement (a timeout reads as one)."""
        if "interrupted" in str(exc).lower():
            return ConnectorError(f"Reading the table took longer than {self._timeout_s:.0f} s")
        return ConnectorError(f"Unable to read SQLite table: {exc}")

    def run(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        self._deadline = time.monotonic() + self._timeout_s
        try:
            return self.conn.execute(sql, params)
        except sqlite3.DatabaseError as exc:
            raise self.error(exc) from exc

    def close(self) -> None:
        self.conn.close()


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def list_tables(
    raw: bytes, limits: ConnectorLimits | None = None, *, timeout_s: float = DEFAULT_TIMEOUT_S
) -> list[dict[str, Any]]:
    """Return ``[{name, hidden}]`` for every ordinary table, in schema order."""
    db = _Database(raw, limits or ConnectorLimits(), timeout_s)
    try:
        return [{"name": t, "hidden": False} for t in db.tables]
    finally:
        db.close()


def read_table(
    raw: bytes,
    table: str | None = None,
    *,
    limits: ConnectorLimits | None = None,
    max_rows: int | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> SourceTable:
    """Read one table into raw string rows, column names first (first table by default)."""
    lim = limits or ConnectorLimits()
    db = _Database(raw, lim, timeout_s)
    try:
        if not db.tables:
            raise ConnectorError("This database has no tables to import")
        if table is None:
            table = db.tables[0]
        elif table not in db.tables:
            raise ConnectorError(f"Table '{table}' not found")
        cap = min(max_rows or lim.max_rows, lim.max_rows)
        cur = db.run(f"SELECT * FROM main.{_quote(table)} LIMIT ?", (cap + 1,))
        names = [d[0] for d in cur.description or ()]
        warnings = list(db.warnings)
        if len(names) > lim.max_columns:
            warnings.append(f"Only the first {lim.max_columns} of {len(names)} columns are read")
            names = names[: lim.max_columns]
        width = len(names)
        rows: list[list[str]] = [[n[: lim.max_cell_chars] for n in names]]
        blob_columns: set[str] = set()
        truncated = False
        try:
            for values in cur:
                if len(rows) > cap:
                    truncated = True
                    break
                row = []
                for i, v in enumerate(values[:width]):
                    if isinstance(v, bytes):
                        blob_columns.add(names[i])
                        row.append("")
                    else:
                        row.append(cell_to_text(v)[: lim.max_cell_chars])
                rows.append(row)
        except sqlite3.DatabaseError as exc:
            raise db.error(exc) from exc
        if blob_columns:
            warnings.append(
                "Binary (BLOB) values are not imported; they are empty in: "
                + ", ".join(sorted(blob_columns))
            )
        if truncated and max_rows is None:
            warnings.append(f"Table truncated at {cap:,} rows")
        return SourceTable(rows=rows, truncated=truncated, sheet=table, warnings=warnings)
    finally:
        db.close()
