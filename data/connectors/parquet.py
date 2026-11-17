"""Parquet connector (.parquet) — one table per file, read in batches.

Parquet is already typed, but Prism still reads it into canonical text and
types it once against the column contract, so a Parquet import is reviewed,
versioned and refreshed exactly like a spreadsheet. The first row returned is
the column names.

Safety: the file is parsed by pyarrow (which no longer unpickles Python
extension types, CVE-2023-47248), only the first ``max_columns`` columns are
decoded, and rows are read in batches up to ``max_rows``.
"""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from typing import Any

from core.errors import ConnectorError
from data.connectors.base import ConnectorLimits, SourceTable
from data.connectors.spreadsheet import cell_to_text

PARQUET_MAGIC = b"PAR1"
_BATCH_ROWS = 10_000


def is_parquet(raw: bytes) -> bool:
    return len(raw) >= 12 and raw.startswith(PARQUET_MAGIC) and raw.endswith(PARQUET_MAGIC)


def _text(value: Any, notes: set[str], column: str) -> str:
    if isinstance(value, bytes):
        notes.add(f"binary:{column}")
        return ""
    if isinstance(value, datetime) and value.tzinfo is not None:
        notes.add(f"utc:{column}")
        value = value.astimezone(UTC).replace(tzinfo=None)
    if isinstance(value, dict | list | tuple):
        notes.add(f"nested:{column}")
        return json.dumps(value, default=str, ensure_ascii=False)
    return cell_to_text(value)


def read_parquet(
    raw: bytes,
    *,
    limits: ConnectorLimits | None = None,
    max_rows: int | None = None,
) -> SourceTable:
    """Read a Parquet file into raw string rows, column names first."""
    lim = limits or ConnectorLimits()
    if not is_parquet(raw):
        raise ConnectorError("Not a Parquet file (missing 'PAR1' markers)")
    import pyarrow as pa
    import pyarrow.parquet as pq

    try:
        pf = pq.ParquetFile(io.BytesIO(raw))
        names = list(pf.schema_arrow.names)
    except (pa.ArrowException, OSError, ValueError) as exc:
        raise ConnectorError(f"Unable to read Parquet file: {exc}") from exc
    if not names:
        raise ConnectorError("This Parquet file has no columns")

    warnings: list[str] = []
    if len(names) > lim.max_columns:
        warnings.append(f"Only the first {lim.max_columns} of {len(names)} columns are read")
        names = names[: lim.max_columns]
    if len(set(names)) != len(names):
        raise ConnectorError("This Parquet file has duplicate column names")

    cap = min(max_rows or lim.max_rows, lim.max_rows)
    rows: list[list[str]] = [[n[: lim.max_cell_chars] for n in names]]
    notes: set[str] = set()
    truncated = False
    try:
        for batch in pf.iter_batches(batch_size=_BATCH_ROWS, columns=names):
            columns = [batch.column(i).to_pylist() for i in range(batch.num_columns)]
            for values in zip(*columns, strict=True):
                if len(rows) > cap:
                    truncated = True
                    break
                rows.append(
                    [
                        _text(v, notes, names[i])[: lim.max_cell_chars]
                        for i, v in enumerate(values)
                    ]
                )
            if truncated:
                break
    except (pa.ArrowException, OSError, ValueError) as exc:
        raise ConnectorError(f"Unable to read Parquet file: {exc}") from exc

    def _cols(kind: str) -> str:
        return ", ".join(sorted(n.split(":", 1)[1] for n in notes if n.startswith(kind + ":")))

    if binary := _cols("binary"):
        warnings.append(f"Binary values are not imported; they are empty in: {binary}")
    if nested := _cols("nested"):
        warnings.append(f"Nested values (lists, structs, maps) are imported as JSON text: {nested}")
    if utc := _cols("utc"):
        warnings.append(f"Timestamps with a time zone are converted to UTC: {utc}")
    if truncated and max_rows is None:
        warnings.append(f"File truncated at {cap:,} rows")
    return SourceTable(rows=rows, truncated=truncated, warnings=warnings)
