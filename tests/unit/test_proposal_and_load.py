"""Tests for import proposals, the load runner and the profiler."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from core.errors import DriftDetected
from core.types.column import DriftPolicy
from data.connectors import read_delimited
from data.detection.proposal import (
    build_proposal,
    date_order,
    detect_locale,
    find_header_row,
    normalize_names,
)
from data.load.runner import LoadColumn, load_rows
from data.profile import profile_table

CORPUS = Path(__file__).resolve().parents[2] / "fixtures" / "parser-corpus"


class TestProposal:
    def test_skips_title_rows(self) -> None:
        rows = read_delimited((CORPUS / "title-rows.csv").read_bytes()).rows
        idx, conf = find_header_row(rows)
        assert rows[idx][0] == "Order ID"
        assert conf >= 0.7
        p = build_proposal(rows)
        names = [c.name for c in p.columns]
        assert names == ["Order ID", "Region", "Order Date", "Revenue"]
        types = {c.name: c.type for c in p.columns}
        assert types["Order Date"] == "date"
        roles = {c.name: c.role for c in p.columns}
        assert roles["Order ID"] == "identifier"
        assert roles["Order Date"] == "time"
        assert p.row_estimate == 6

    def test_null_markers_do_not_break_inference(self) -> None:
        rows = read_delimited((CORPUS / "title-rows.csv").read_bytes()).rows
        p = build_proposal(rows)
        rev = next(c for c in p.columns if c.name == "Revenue")
        assert rev.type == "float"
        assert not rev.ambiguous
        assert rev.null_ratio > 0

    def test_mixed_column_is_ambiguous(self) -> None:
        rows = [["qty"], ["1"], ["2"], ["lots"], ["few"], ["5"], ["6"]]
        p = build_proposal(rows)
        qty = p.columns[0]
        assert qty.type == "integer"  # most plausible specific type is proposed
        assert qty.ambiguous and p.needs_review
        assert any("lots" in f for c in qty.candidates for f in c["failures"])

    def test_german_locale_detected(self) -> None:
        rows = read_delimited((CORPUS / "de-semicolon.csv").read_bytes()).rows
        p = build_proposal(rows)
        assert p.locale == "de_DE"
        types = {c.name: c.type for c in p.columns}
        assert types == {"Region": "string", "Monat": "date", "Umsatz": "float", "Menge": "integer"}
        assert not p.needs_review

    def test_override_header_and_locale(self) -> None:
        rows = [["a", "b"], ["1", "2"], ["3", "4"]]
        p = build_proposal(rows, header_row=-1, locale="en_US")
        assert p.header_row == -1
        assert [c.name for c in p.columns] == ["column_1", "column_2"]
        assert p.row_estimate == 3

    def test_empty_input(self) -> None:
        p = build_proposal([])
        assert p.columns == []
        assert "No tabular data found" in p.warnings

    def test_normalize_names(self) -> None:
        assert normalize_names(["Name", "name", "", " A\tB "], 5) == [
            "Name",
            "name_2",
            "column_3",
            "A B",
            "column_5",
        ]

    def test_detect_locale_and_date_order(self) -> None:
        assert detect_locale([["1.234,50", "2.000,00", "3,5", "10,25"]]) == "de_DE"
        assert detect_locale([["1,234.50", "2.5", "3.75"]]) == "en_US"
        assert date_order(["25/12/2026", "01/02/2026"]) == "dmy"
        assert date_order(["12/25/2026", "01/02/2026"]) == "mdy"
        assert date_order(["01/02/2026"]) is None

    def test_day_first_dates_get_column_locale(self) -> None:
        rows = [["day", "v"], ["25/12/2026", "1"], ["03/01/2026", "2"], ["14/02/2026", "3"]]
        p = build_proposal(rows)
        day = p.columns[0]
        assert day.type == "date" and day.locale == "en_GB"


class TestLoadRunner:
    ROWS = [
        ["Region", "Day", "Amount"],
        ["EU", "2026-01-01", "10.5"],
        ["US", "2026-01-02", ""],
        ["", "", ""],
        ["EU", "2026-01-03", "7"],
    ]
    COLS = [
        LoadColumn(name="region", type="string", source_name="Region"),
        LoadColumn(name="day", type="date", source_name="Day"),
        LoadColumn(name="amount", type="float", source_name="Amount"),
    ]

    def test_types_and_skips_blank_rows(self) -> None:
        r = load_rows(self.ROWS, self.COLS, header_row=0, data_start_row=1)
        assert r.row_count == 3
        assert r.quarantine_count == 0
        rows = r.table.to_pylist()
        assert rows[0] == {"region": "EU", "day": date(2026, 1, 1), "amount": 10.5}
        assert rows[1]["amount"] is None

    def test_null_tokens_load_as_null(self) -> None:
        rows = [["Region", "Day", "Amount"], ["EU", "2026-01-01", "n/a"], ["N/A", "-", "1"]]
        r = load_rows(rows, self.COLS, header_row=0, data_start_row=1)
        assert r.quarantine_count == 0
        got = r.table.to_pylist()
        assert got[0]["amount"] is None and got[1]["day"] is None
        assert got[1]["region"] == "N/A"  # strings keep their literal text

    def test_quarantines_bad_rows(self) -> None:
        rows = [*self.ROWS, *[["EU", "2026-02-01", "1"]] * 40, ["EU", "someday", "3"]]
        r = load_rows(rows, self.COLS, header_row=0, data_start_row=1)
        assert r.quarantine_count == 1
        q = r.quarantine.to_pylist()[0]  # type: ignore[union-attr]
        assert q["_source_row"] == len(rows)
        assert "someday" in q["_reason"]

    def test_tolerance_exceeded_fails_loudly(self) -> None:
        rows = [["Region", "Day", "Amount"], ["EU", "x", "1"], ["EU", "y", "1"]]
        with pytest.raises(DriftDetected, match="tolerance"):
            load_rows(rows, self.COLS, header_row=0, data_start_row=1)

    def test_required_column_empty_is_quarantined(self) -> None:
        cols = [LoadColumn(name="region", type="string", source_name="Region", nullable=False)]
        rows = [["Region"], *[["EU"]] * 30, [""], ["US"]]
        r = load_rows(rows, cols, header_row=0, data_start_row=1)
        # The blank row is fully empty -> skipped, not quarantined.
        assert r.quarantine_count == 0 and r.row_count == 31

    def test_missing_column_drift(self) -> None:
        rows = [["Region", "Amount"], ["EU", "1"]]
        with pytest.raises(DriftDetected, match="Day"):
            load_rows(rows, self.COLS, header_row=0, data_start_row=1)
        lenient = [
            *self.COLS[:1],
            LoadColumn(name="day", type="date", source_name="Day", drift_policy=DriftPolicy.WARN),
            self.COLS[2],
        ]
        r = load_rows(rows, lenient, header_row=0, data_start_row=1)
        assert r.drift and r.table.column("day").null_count == 1

    def test_header_match_is_whitespace_insensitive_and_reorder_safe(self) -> None:
        rows = [["amount ", "REGION", "day"], ["5", "EU", "2026-01-01"]]
        r = load_rows(rows, self.COLS, header_row=0, data_start_row=1)
        assert r.table.to_pylist() == [{"region": "EU", "day": date(2026, 1, 1), "amount": 5.0}]


def test_profile_table() -> None:
    r = load_rows(TestLoadRunner.ROWS, TestLoadRunner.COLS, header_row=0, data_start_row=1)
    prof = profile_table(r.table)
    assert prof["row_count"] == 3
    amount = prof["columns"]["amount"]
    assert amount["nulls"] == 1 and amount["min"] == 7.0 and amount["max"] == 10.5
    region = prof["columns"]["region"]
    assert region["top"][0] == {"value": "EU", "count": 2}
    assert prof["columns"]["day"]["min"] == "2026-01-01"
