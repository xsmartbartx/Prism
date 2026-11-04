"""Tests for delimited and spreadsheet connectors."""

from __future__ import annotations

import io
import zipfile
from datetime import date, datetime
from pathlib import Path

import pytest
from openpyxl import Workbook

from core.errors import ConnectorError
from data.connectors import list_sheets, read_delimited, read_sheet
from data.connectors.delimited import sniff_delimiter
from data.connectors.spreadsheet import cell_to_text

CORPUS = Path(__file__).resolve().parents[2] / "fixtures" / "parser-corpus"


def _xlsx(build) -> bytes:  # type: ignore[no-untyped-def]
    wb = Workbook()
    build(wb)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestDelimited:
    def test_semicolon_and_encoding(self) -> None:
        t = read_delimited((CORPUS / "de-semicolon.csv").read_bytes())
        assert t.delimiter == ";"
        assert t.rows[0] == ["Region", "Monat", "Umsatz", "Menge"]
        assert t.rows[2][0] == "Süd"

    def test_cp1252_fallback(self) -> None:
        raw = "name,city\nZoë,Köln\n".encode("cp1252")
        t = read_delimited(raw)
        assert t.rows[1] == ["Zoë", "Köln"]

    def test_tab_sniff(self) -> None:
        assert sniff_delimiter("a\tb\tc\n1\t2\t3\n") == "\t"

    def test_max_rows_truncates(self) -> None:
        raw = ("a,b\n" + "1,2\n" * 50).encode()
        t = read_delimited(raw, max_rows=10)
        assert len(t.rows) == 10 and t.truncated

    def test_binary_rejected(self) -> None:
        with pytest.raises(ConnectorError):
            read_delimited(b"\x00\x01\x02binary")


class TestSpreadsheet:
    def test_reads_typed_cells_canonically(self) -> None:
        def build(wb: Workbook) -> None:
            ws = wb.active
            ws.title = "Sales"
            ws.append(["Region", "When", "Amount", "Units", "Flag"])
            ws.append(["EU", datetime(2026, 1, 5), 12.5, 3.0, True])
            ws.append(["US", date(2026, 2, 1), 7, 4, False])
            hidden = wb.create_sheet("Secret")
            hidden.sheet_state = "hidden"

        raw = _xlsx(build)
        sheets = list_sheets(raw)
        assert sheets == [{"name": "Sales", "hidden": False}, {"name": "Secret", "hidden": True}]
        t = read_sheet(raw)
        assert t.sheet == "Sales"
        assert t.rows[1] == ["EU", "2026-01-05", "12.5", "3", "true"]
        assert t.rows[2] == ["US", "2026-02-01", "7", "4", "false"]

    def test_formulas_are_not_evaluated(self) -> None:
        def build(wb: Workbook) -> None:
            ws = wb.active
            ws.append(["a", "b"])
            ws.append([1, "=1+1"])

        t = read_sheet(_xlsx(build))
        # No cached value exists (never opened in Excel) -> empty, never computed.
        assert t.rows[1][0] == "1"
        assert len(t.rows[1]) == 1 or t.rows[1][1] in ("", "=1+1")

    def test_missing_sheet(self) -> None:
        raw = _xlsx(lambda wb: wb.active.append(["x"]))
        with pytest.raises(ConnectorError):
            read_sheet(raw, "Nope")

    def test_rejects_non_workbook(self) -> None:
        with pytest.raises(ConnectorError):
            read_sheet(b"hello")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("readme.txt", "hi")
        with pytest.raises(ConnectorError):
            read_sheet(buf.getvalue())

    def test_zip_bomb_guard(self) -> None:
        from data.connectors.base import ConnectorLimits

        raw = _xlsx(lambda wb: wb.active.append(["x"] * 10))
        with pytest.raises(ConnectorError):
            read_sheet(raw, limits=ConnectorLimits(max_uncompressed_bytes=100))

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, ""),
            (3.0, "3"),
            (0.1, "0.1"),
            ("#DIV/0!", ""),
            ("#N/A", ""),
            ("Hello", "Hello"),
            (datetime(2026, 1, 1, 13, 30), "2026-01-01 13:30:00"),
        ],
    )
    def test_cell_to_text(self, value: object, expected: str) -> None:
        assert cell_to_text(value) == expected
