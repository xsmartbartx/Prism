"""Exports neutralise formula injection and keep types."""

from __future__ import annotations

import io
from datetime import date

from openpyxl import load_workbook

from presentation.export import neutralize, to_csv, to_xlsx


def test_neutralize() -> None:
    assert neutralize("=HYPERLINK(\"http://evil\")") == "'=HYPERLINK(\"http://evil\")"
    assert neutralize("+1") == "'+1"
    assert neutralize("@SUM(A1)") == "'@SUM(A1)"
    assert neutralize("safe") == "safe"
    assert neutralize(-5) == -5


def test_csv() -> None:
    data = to_csv(["a", "b"], [{"a": "=1+1", "b": date(2026, 1, 2)}, {"a": None, "b": -3}])
    text = data.decode("utf-8-sig")
    assert text.splitlines() == ["a,b", "'=1+1,2026-01-02", ",-3"]


def test_xlsx() -> None:
    data = to_xlsx(["name", "value"], [{"name": "-cmd", "value": -2.5}])
    ws = load_workbook(io.BytesIO(data)).active
    assert ws["A2"].value == "'-cmd"
    assert ws["B2"].value == -2.5
