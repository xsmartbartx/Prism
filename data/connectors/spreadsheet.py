"""Spreadsheet connector (.xlsx / .xlsm) — streaming, values only.

Safety posture (architecture §13.4, single-node edition):
  * the archive is inspected before parsing: total uncompressed size and
    compression ratio are capped (zip-bomb guard);
  * openpyxl runs in ``read_only`` streaming mode with ``data_only=True``,
    so cached values are read and formulas are never evaluated;
  * XML is parsed through ``defusedxml`` when installed (XXE guard);
  * macros in .xlsm are ignored — VBA is never extracted or run.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from core.errors import ConnectorError
from data.connectors.base import ConnectorLimits, SourceTable

try:  # pragma: no cover - import guard
    import defusedxml  # noqa: F401

    _DEFUSED = True
except ImportError:  # pragma: no cover
    _DEFUSED = False


def _check_archive(raw: bytes, lim: ConnectorLimits) -> None:
    if not raw.startswith(b"PK"):
        raise ConnectorError("Not an .xlsx workbook (expected a zip archive)")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            infos = zf.infolist()
    except zipfile.BadZipFile as exc:
        raise ConnectorError(f"Corrupt workbook archive: {exc}") from exc
    total = sum(i.file_size for i in infos)
    if total > lim.max_uncompressed_bytes:
        raise ConnectorError("Workbook expands beyond the allowed size")
    compressed = max(sum(i.compress_size for i in infos), 1)
    if total / compressed > lim.max_compression_ratio and total > 50 * 1024 * 1024:
        raise ConnectorError("Workbook compression ratio is suspicious (possible zip bomb)")
    names = {i.filename for i in infos}
    if "xl/workbook.xml" not in names:
        raise ConnectorError("Archive is not an Excel workbook")


def _open(raw: bytes, lim: ConnectorLimits) -> Any:
    _check_archive(raw, lim)
    from openpyxl import load_workbook

    try:
        return load_workbook(io.BytesIO(raw), read_only=True, data_only=True, keep_links=False)
    except Exception as exc:
        raise ConnectorError(f"Unable to read workbook: {exc}") from exc


def list_sheets(raw: bytes, limits: ConnectorLimits | None = None) -> list[dict[str, Any]]:
    """Return ``[{name, hidden}]`` for every worksheet."""
    lim = limits or ConnectorLimits()
    wb = _open(raw, lim)
    try:
        out = []
        for ws in wb.worksheets:
            out.append({"name": ws.title, "hidden": ws.sheet_state != "visible"})
        return out
    finally:
        wb.close()


def cell_to_text(value: Any) -> str:
    """Canonical, locale-free text for a typed cell value."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        if value.time() == time(0, 0):
            return value.date().isoformat()
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return repr(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    text = str(value)
    if text.startswith("#") and text.endswith(("!", "?", "A")) and text.isupper():
        return ""  # Excel error values (#DIV/0!, #N/A, #NAME?) become nulls
    return text


def read_sheet(
    raw: bytes,
    sheet: str | None = None,
    *,
    limits: ConnectorLimits | None = None,
    max_rows: int | None = None,
) -> SourceTable:
    """Stream one worksheet into raw string rows (first visible sheet by default)."""
    lim = limits or ConnectorLimits()
    wb = _open(raw, lim)
    try:
        if sheet is None:
            visible = [ws for ws in wb.worksheets if ws.sheet_state == "visible"]
            if not visible:
                raise ConnectorError("Workbook has no visible sheets")
            ws = visible[0]
        else:
            if sheet not in wb.sheetnames:
                raise ConnectorError(f"Sheet '{sheet}' not found")
            ws = wb[sheet]
        cap = min(max_rows or lim.max_rows, lim.max_rows)
        rows: list[list[str]] = []
        truncated = False
        for values in ws.iter_rows(values_only=True):
            if len(rows) >= cap:
                truncated = True
                break
            row = [cell_to_text(v)[: lim.max_cell_chars] for v in values[: lim.max_columns]]
            while row and row[-1] == "":
                row.pop()
            rows.append(row)
        while rows and not rows[-1]:
            rows.pop()
        warnings = []
        if truncated and max_rows is None:
            warnings.append(f"Sheet truncated at {cap:,} rows")
        if not _DEFUSED:  # pragma: no cover
            warnings.append("defusedxml not installed; XML hardening disabled")
        return SourceTable(rows=rows, truncated=truncated, sheet=ws.title, warnings=warnings)
    finally:
        wb.close()
