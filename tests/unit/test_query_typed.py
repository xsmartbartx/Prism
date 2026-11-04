"""Typed compiler validation and the extended in-memory executor."""

from __future__ import annotations

from datetime import date

import pytest

from data.query import (
    AggFunction,
    AggregationSpec,
    FilterOp,
    FilterSpec,
    QueryCompiler,
    QueryExecutor,
    QuerySpec,
    SortDir,
    SortSpec,
    TimeGrain,
)

TYPES = {"region": "string", "day": "date", "amount": "float", "units": "integer", "ok": "boolean"}
ROWS = [
    {"region": "EU", "day": date(2026, 1, 5), "amount": 10.0, "units": 1, "ok": True},
    {"region": "EU", "day": date(2026, 1, 20), "amount": 30.0, "units": 3, "ok": False},
    {"region": "US", "day": date(2026, 2, 2), "amount": 5.0, "units": 2, "ok": True},
    {"region": "APAC", "day": date(2026, 4, 1), "amount": None, "units": 7, "ok": True},
]


def run(spec: QuerySpec) -> list[dict[str, object]]:
    res = QueryCompiler(column_types=TYPES).compile(spec)
    assert res.success, res.errors
    assert res.plan is not None
    return list(QueryExecutor().execute(res.plan, ROWS).rows)


class TestTypedValidation:
    @pytest.mark.parametrize(
        ("spec", "fragment"),
        [
            (QuerySpec(dimensions=["day"], measures=[AggregationSpec(column="region", function=AggFunction.SUM)]), "Cannot sum"),
            (QuerySpec(filters=[FilterSpec(column="day", operator=FilterOp.GT, value="not-a-date")]), "valid date"),
            (QuerySpec(filters=[FilterSpec(column="amount", operator=FilterOp.CONTAINS, value="x")]), "text columns"),
            (QuerySpec(filters=[FilterSpec(column="region", operator=FilterOp.IN, value=[])]), "non-empty list"),
            (QuerySpec(filters=[FilterSpec(column="units", operator=FilterOp.BETWEEN, value=[1])]), "between"),
            (QuerySpec(dimensions=["region"], time_grain={"region": TimeGrain.MONTH}), "date column"),
            (QuerySpec(dimensions=["region"], measures=[AggregationSpec(column="amount", function=AggFunction.SUM), AggregationSpec(column="amount", function=AggFunction.AVG)]), "collide"),
            (QuerySpec(dimensions=["region"], sort=[SortSpec(column="units")]), "Sort column"),
            (QuerySpec(measures=[AggregationSpec(column="*", function=AggFunction.SUM)]), "Only count"),
            (QuerySpec(dimensions=["region"], columns=["region"]), "cannot combine"),
        ],
    )
    def test_rejects(self, spec: QuerySpec, fragment: str) -> None:
        res = QueryCompiler(column_types=TYPES).compile(spec)
        assert not res.success
        assert any(fragment in e for e in res.errors), res.errors

    def test_limit_is_clamped(self) -> None:
        res = QueryCompiler(column_types=TYPES, max_limit=100).compile(QuerySpec(limit=10_000))
        assert res.plan is not None and res.plan.limit == 100


class TestExtendedExecution:
    def test_month_grain_and_aliases(self) -> None:
        rows = run(
            QuerySpec(
                dimensions=["day"],
                time_grain={"day": TimeGrain.MONTH},
                measures=[
                    AggregationSpec(column="amount", function=AggFunction.SUM, alias="revenue"),
                    AggregationSpec(column="*", function=AggFunction.COUNT),
                ],
                sort=[SortSpec(column="day")],
            )
        )
        assert rows[0] == {"day": date(2026, 1, 1), "revenue": 40.0, "count": 2}
        assert [r["day"] for r in rows] == [date(2026, 1, 1), date(2026, 2, 1), date(2026, 4, 1)]

    def test_grand_total(self) -> None:
        rows = run(QuerySpec(measures=[AggregationSpec(column="units", function=AggFunction.SUM)]))
        assert rows == [{"units": 13}]

    def test_filters(self) -> None:
        rows = run(
            QuerySpec(
                columns=["region"],
                filters=[
                    FilterSpec(column="day", operator=FilterOp.GTE, value="2026-01-10"),
                    FilterSpec(column="region", operator=FilterOp.IN, value=["EU", "US"]),
                ],
                sort=[SortSpec(column="region", direction=SortDir.DESC)],
            )
        )
        assert rows == [{"region": "US"}, {"region": "EU"}]
        assert run(QuerySpec(columns=["region"], filters=[FilterSpec(column="amount", operator=FilterOp.IS_NULL, value=None)])) == [{"region": "APAC"}]
        assert len(run(QuerySpec(columns=["region"], filters=[FilterSpec(column="region", operator=FilterOp.CONTAINS, value="u")]))) == 3
        assert len(run(QuerySpec(columns=["units"], filters=[FilterSpec(column="units", operator=FilterOp.BETWEEN, value=[2, 3])]))) == 2

    def test_median_and_distinct(self) -> None:
        rows = run(
            QuerySpec(
                measures=[
                    AggregationSpec(column="units", function=AggFunction.MEDIAN, alias="med"),
                    AggregationSpec(column="region", function=AggFunction.COUNT_DISTINCT, alias="regions"),
                ]
            )
        )
        assert rows == [{"med": 2.5, "regions": 3}]
