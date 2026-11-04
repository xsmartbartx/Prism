"""Tabular exports.

Any text cell beginning with a formula trigger (``= + - @``, tab or
carriage return) is prefixed with an apostrophe so a spreadsheet opens
it as text instead of executing it (CSV/formula injection, OWASP).
Numbers keep their numeric type, so negative values are untouched.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import Any

_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def neutralize(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(_TRIGGERS):
        return "'" + value
    return value


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return neutralize(value)


def to_csv(columns: list[str], rows: list[dict[str, Any]]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow([neutralize(c) for c in columns])
    for r in rows:
        w.writerow([_cell(r.get(c)) for c in columns])
    return ("﻿" + buf.getvalue()).encode("utf-8")  # BOM: Excel opens UTF-8 correctly


def to_xlsx(columns: list[str], rows: list[dict[str, Any]], *, sheet: str = "Data") -> bytes:
    from openpyxl import Workbook
    from openpyxl.cell.cell import WriteOnlyCell
    from openpyxl.styles import Font

    wb = Workbook(write_only=True)
    ws = wb.create_sheet(title=(sheet or "Data")[:31])
    header = []
    for c in columns:
        cell = WriteOnlyCell(ws, value=neutralize(c))
        cell.font = Font(bold=True)
        header.append(cell)
    ws.append(header)
    for r in rows:
        out = []
        for c in columns:
            v = r.get(c)
            if isinstance(v, str):
                v = neutralize(v)
            out.append(v)
        ws.append(out)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
