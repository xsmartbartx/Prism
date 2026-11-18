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
