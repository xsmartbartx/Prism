"""Dashboard filter logic: definitions, selections from query parameters, application."""

from __future__ import annotations

from datetime import date

import pytest

from data.query import QuerySpec
from data.query.spec import FilterOp, FilterSpec
from server.errors import BadRequest
from server.services.dashboard_filters import (
    MAX_FILTERS,
    MAX_SELECTED,
    apply_selections,
    clean_definitions,
    encode_selections,
    parse_selections,
)

AVAILABLE = {"Region": {"string"}, "Order Date": {"date"}, "Revenue": {"float"}, "Year": {"integer", "string"}}
DEFS = [
    {"field": "Region", "kind": "values", "label": "Region"},
    {"field": "Order Date", "kind": "date_range", "label": "Ordered"},
]


class TestDefinitions:
    def test_cleans_and_defaults_label(self) -> None:
        out = clean_definitions(
            [{"field": " Region "}, {"field": "Order Date", "kind": "date_range", "label": " Ordered "}],
            AVAILABLE,
        )
        assert out == [
            {"field": "Region", "kind": "values", "label": "Region"},
            {"field": "Order Date", "kind": "date_range", "label": "Ordered"},
        ]

    def test_fields_match_ignoring_case_and_spacing(self) -> None:
        out = clean_definitions([{"field": "region"}, {"field": "order  date", "kind": "date_range"}], AVAILABLE)
        assert [f["field"] for f in out] == ["region", "order  date"]
        with pytest.raises(BadRequest, match="twice"):
            clean_definitions([{"field": "Region"}, {"field": "REGION "}], AVAILABLE)

    @pytest.mark.parametrize(
        ("items", "message"),
        [
            ([{"field": ""}], "needs a field"),
            ([{"field": "Nope"}], "No chart"),
            ([{"field": "Region", "kind": "date_range"}], "not a date"),
            ([{"field": "Revenue"}], "decimals"),
            ([{"field": "Region"}, {"field": "Region"}], "twice"),
            ([{"field": "Region", "kind": "slider"}], "Unknown filter kind"),
            ([{"field": "Region"}] * (MAX_FILTERS + 1), "at most"),
        ],
    )
    def test_rejects(self, items: list[dict[str, str]], message: str) -> None:
        with pytest.raises(BadRequest, match=message):
            clean_definitions(items, AVAILABLE)


class TestSelections:
    def test_parses_values_and_ranges(self) -> None:
        params = [
            ("fv0", "EU"), ("fv0", "US"), ("fv0", "EU"), ("fv0", " "),
            ("ff1", "2026-03-31"), ("ft1", "2026-01-01"),  # reversed: swapped
            ("theme", "dark"), ("fv9", "x"), ("fvx", "y"), ("ff1x", "z"),
        ]
        sel = parse_selections(DEFS, params)
        assert [(s.field, s.values) for s in sel if s.kind == "values"] == [("Region", ("EU", "US"))]
        rng = next(s for s in sel if s.kind == "date_range")
        assert (rng.start, rng.end, rng.label) == (date(2026, 1, 1), date(2026, 3, 31), "Ordered")
        assert parse_selections(DEFS, encode_selections(sel)) == sel

    def test_ignores_bad_dates_long_values_and_caps_count(self) -> None:
        params = [("ff1", "soon"), ("ft1", ""), ("fv0", "x" * 201)]
        assert parse_selections(DEFS, params) == []
        many = parse_selections(DEFS, [("fv0", str(i)) for i in range(MAX_SELECTED + 50)])
        assert len(many[0].values) == MAX_SELECTED

    def test_open_ended_range(self) -> None:
        (sel,) = parse_selections(DEFS, [("ff1", "2026-02-01")])
        assert sel.start == date(2026, 2, 1) and sel.end is None


class TestApply:
    BASE = QuerySpec(
        dimensions=["Region"], filters=[FilterSpec(column="Revenue", operator=FilterOp.GT, value=0)]
    )

    def test_ands_onto_existing_filters(self) -> None:
        sel = parse_selections(DEFS, [("fv0", "EU"), ("ff1", "2026-01-01"), ("ft1", "2026-01-31")])
        types = {"Region": "string", "Order Date": "date", "Revenue": "float"}
        spec, applied, skipped = apply_selections(self.BASE, types, sel)
        assert applied == ["Region", "Ordered"] and skipped == []
        assert [(f.column, f.operator, f.value) for f in spec.filters] == [
            ("Revenue", FilterOp.GT, 0),
            ("Region", FilterOp.IN, ["EU"]),
            ("Order Date", FilterOp.GTE, "2026-01-01"),
            ("Order Date", FilterOp.LTE, "2026-01-31"),
        ]
        assert self.BASE.filters == [FilterSpec(column="Revenue", operator=FilterOp.GT, value=0)]

    def test_skips_missing_fields_and_unreadable_values(self) -> None:
        sel = parse_selections(DEFS, [("fv0", "EU"), ("ff1", "2026-01-01")])
        # Region is an integer here, so "EU" cannot select anything; Order Date is text.
        spec, applied, skipped = apply_selections(
            self.BASE, {"Region": "integer", "Order Date": "string"}, sel
        )
        assert applied == [] and skipped == ["Region", "Ordered"]
        assert spec is self.BASE
        _, applied, skipped = apply_selections(self.BASE, {"Revenue": "float"}, sel)
        assert skipped == ["Region", "Ordered"]

    def test_matches_columns_ignoring_case(self) -> None:
        sel = parse_selections(DEFS, [("fv0", "EU"), ("ff1", "2026-01-01")])
        spec, applied, skipped = apply_selections(
            QuerySpec(), {"region": "string", "ORDER DATE": "date"}, sel
        )
        assert applied == ["Region", "Ordered"] and skipped == []
        assert [f.column for f in spec.filters] == ["region", "ORDER DATE"]

    def test_keeps_only_readable_values(self) -> None:
        sel = parse_selections([{"field": "Year", "kind": "values"}], [("fv0", "2026"), ("fv0", "next")])
        spec, applied, _ = apply_selections(QuerySpec(), {"Year": "integer"}, sel)
        assert applied == ["Year"] and spec.filters[0].value == ["2026"]


def test_non_ascii_digit_indices_are_ignored() -> None:
    sel = parse_selections(DEFS, [("fv²", "x"), ("ff٣", "2026-01-01"), ("fv0", "EU")])
    assert [(s.field, s.values) for s in sel] == [("Region", ("EU",))]


class TestRelativePeriods:
    TODAY = date(2026, 11, 27)

    @pytest.mark.parametrize(
        ("preset", "today", "start", "end"),
        [
            ("last_7_days", date(2026, 11, 27), date(2026, 11, 21), date(2026, 11, 27)),
            ("last_30_days", date(2026, 3, 1), date(2026, 1, 31), date(2026, 3, 1)),
            ("last_90_days", date(2026, 11, 27), date(2026, 8, 30), date(2026, 11, 27)),
            ("this_month", date(2026, 2, 10), date(2026, 2, 1), date(2026, 2, 28)),
            ("last_month", date(2026, 1, 15), date(2025, 12, 1), date(2025, 12, 31)),
            ("last_month", date(2026, 3, 31), date(2026, 2, 1), date(2026, 2, 28)),
            ("this_quarter", date(2026, 11, 27), date(2026, 10, 1), date(2026, 12, 31)),
            ("last_quarter", date(2026, 2, 3), date(2025, 10, 1), date(2025, 12, 31)),
            ("last_quarter", date(2026, 11, 27), date(2026, 7, 1), date(2026, 9, 30)),
            ("this_year", date(2026, 11, 27), date(2026, 1, 1), date(2026, 12, 31)),
            ("last_year", date(2026, 1, 1), date(2025, 1, 1), date(2025, 12, 31)),
            ("last_12_months", date(2026, 11, 27), date(2025, 11, 1), date(2026, 10, 31)),
            ("last_12_months", date(2026, 1, 5), date(2025, 1, 1), date(2025, 12, 31)),
        ],
    )
    def test_periods(self, preset: str, today: date, start: date, end: date) -> None:
        from server.services.dashboard_filters import preset_range

        assert preset_range(preset, today) == (start, end)

    def test_every_preset_resolves(self) -> None:
        from server.services.dashboard_filters import PRESETS, preset_range

        for p in PRESETS:
            first, last = preset_range(p, self.TODAY)
            assert first <= last

    def test_selected_period_and_default(self) -> None:
        defs = [DEFS[0], {**DEFS[1], "default": "last_month"}]
        picked = parse_selections(defs, [("fr1", "this_year")], today=self.TODAY)
        assert [(s.start, s.end, s.preset) for s in picked] == [(date(2026, 1, 1), date(2026, 12, 31), "this_year")]
        # Nothing said about the filter: its default period, worked out from today.
        default = parse_selections(defs, [("fv0", "EU")], today=self.TODAY)
        assert (default[1].start, default[1].end, default[1].preset) == (date(2026, 10, 1), date(2026, 10, 31), "last_month")
        # "all" clears the default; explicit dates (with or without "custom") replace it.
        assert parse_selections(defs, [("fr1", "all")], today=self.TODAY) == []
        for params in ([("ff1", "2026-01-01")], [("fr1", "custom"), ("ff1", "2026-01-01")]):
            (sel,) = parse_selections(defs, params, today=self.TODAY)
            assert (sel.start, sel.end, sel.preset) == (date(2026, 1, 1), None, None)
        # "custom" without dates, or an unknown period: no filter, and no default sneaking back.
        assert parse_selections(defs, [("fr1", "custom")], today=self.TODAY) == []
        assert parse_selections(defs, [("fr1", "next_decade")], today=self.TODAY) == []

    def test_defaults_are_checked(self) -> None:
        out = clean_definitions([{"field": "Order Date", "kind": "date_range", "default": "last_month"}], AVAILABLE)
        assert out == [{"field": "Order Date", "kind": "date_range", "label": "Order Date", "default": "last_month"}]
        assert "default" not in clean_definitions([{"field": "Order Date", "kind": "date_range", "default": None}], AVAILABLE)[0]
        with pytest.raises(BadRequest, match="Unknown period"):
            clean_definitions([{"field": "Order Date", "kind": "date_range", "default": "someday"}], AVAILABLE)
        with pytest.raises(BadRequest, match="Only a date range"):
            clean_definitions([{"field": "Region", "default": "last_month"}], AVAILABLE)

    def test_links_keep_periods_relative(self) -> None:
        defs = [DEFS[0], {**DEFS[1], "default": "last_month"}]
        for params in ([("fr1", "last_quarter")], [("ff1", "2026-01-01"), ("ft1", "2026-02-01")]):
            sel = parse_selections(defs, params, today=self.TODAY)
            assert parse_selections(defs, encode_selections(sel), today=self.TODAY) == sel
        assert ("fr1", "last_quarter") in encode_selections(parse_selections(defs, [("fr1", "last_quarter")], today=self.TODAY))
