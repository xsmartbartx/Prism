"""Delimited text connector (CSV, TSV, semicolon- and pipe-separated)."""

from __future__ import annotations

import csv
import io

from core.errors import ConnectorError
from data.connectors.base import ConnectorLimits, SourceTable

_ENCODINGS = ("utf-8-sig", "utf-16", "cp1252", "latin-1")
_DELIMITERS = [",", ";", "\t", "|"]


def decode(raw: bytes) -> tuple[str, str]:
    """Decode bytes, trying UTF-8 first and falling back to legacy encodings."""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16"), "utf-16"
    for enc in _ENCODINGS:
        if enc == "utf-16":
            continue
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise ConnectorError("Unable to decode file as text")  # pragma: no cover - latin-1 never fails


def sniff_delimiter(sample: str) -> str:
    """Pick the delimiter that splits the sample most consistently."""
    lines = [ln for ln in sample.splitlines()[:50] if ln.strip()]
    if not lines:
        return ","
    best, best_score = ",", -1.0
    for d in _DELIMITERS:
        counts = [len(next(csv.reader([ln], delimiter=d))) for ln in lines]
        if max(counts) <= 1:
            continue
        mode = max(set(counts), key=counts.count)
        consistency = counts.count(mode) / len(counts)
        score = consistency * 10 + min(mode, 50) / 50
        if score > best_score:
            best, best_score = d, score
    return best


def read_delimited(
    raw: bytes,
    *,
    delimiter: str | None = None,
    limits: ConnectorLimits | None = None,
    max_rows: int | None = None,
) -> SourceTable:
    """Parse delimited text into raw string rows."""
    lim = limits or ConnectorLimits()
    text, encoding = decode(raw)
    if "\x00" in text[:4096]:
        raise ConnectorError("File looks binary, not delimited text")
    delim = delimiter or sniff_delimiter(text[:65536])
    cap = min(max_rows or lim.max_rows, lim.max_rows)
    csv.field_size_limit(lim.max_cell_chars + 1)

    rows: list[list[str]] = []
    truncated = False
    warnings: list[str] = []
    try:
        for row in csv.reader(io.StringIO(text, newline=""), delimiter=delim):
            if len(rows) >= cap:
                truncated = True
                break
            if len(row) > lim.max_columns:
                raise ConnectorError(f"Too many columns ({len(row)} > {lim.max_columns})")
            rows.append(row)
    except csv.Error as exc:
        raise ConnectorError(f"Malformed delimited file: {exc}") from exc
    if truncated and max_rows is None:
        warnings.append(f"File truncated at {cap:,} rows")
    return SourceTable(
        rows=rows, truncated=truncated, encoding=encoding, delimiter=delim, warnings=warnings
    )
