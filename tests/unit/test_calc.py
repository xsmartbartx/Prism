"""Calculated fields: the formula language, its type checks, and execution in DuckDB."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from data.query import QueryCompiler, QuerySpec
from data.query.calc import (
    MAX_CALCULATIONS,
    CalcError,
    build,
    compile_expression,
    needed,
    parse,
    tokenize,
)
from data.query.duck import DuckDBExecutor
from data.query.spec import AggFunction, AggregationSpec, FilterOp, FilterSpec

COLS = {"Revenue": "float", "Cost": "float", "Units": "integer", "Region": "string",
        "Order Date": "date", "Paid": "boolean", 'Odd "name"]': "string"}


def kind(text: str) -> str:
    return compile_expression(text, COLS)[1]


class TestTypes:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("[Revenue] - [Cost]", "float"),
            ("[Units] * 2", "integer"),
            ("[Units] / 2", "float"),
            ("[Units] % 3", "integer"),
            ("-[Units]", "integer"),
            ("ROUND([Revenue])", "float"),
            ("ROUND([Units])", "integer"),
            ("ROUND([Revenue] / [Cost] * 100, 1)", "float"),
            ("ABS([Revenue])", "float"),
            ("FLOOR([Revenue]) + CEIL(1.5)", "integer"),
            ("IF([Units] >= 10, 'Bulk', 'Single')", "string"),
            ("IF([Paid], [Revenue], 0)", "float"),
            ("IF([Paid], [Revenue])", "float"),
            ("COALESCE([Units], 0)", "integer"),
            ("ISEMPTY([Region])", "boolean"),
            ("YEAR([Order Date])", "integer"),
            ("[Order Date] + 7", "date"),
            ("[Order Date] - [Order Date]", "integer"),
            ("DAYS_BETWEEN([Order Date], [Order Date])", "integer"),
            ("[Order Date] >= '2026-01-01'", "boolean"),
            ("'2026-01-01' < [Order Date]", "boolean"),
            ("UPPER([Region]) & ' / ' & [Units]", "string"),
            ("LEN(TRIM([Region]))", "integer"),
            ("LEFT([Region], 2)", "string"),
            ("CONTAINS([Region], 'eu') AND NOT [Paid] OR [Units] > 1", "boolean"),
            ("CONCAT([Region], '-', [Units])", "string"),
            ("[Odd \"name\"]]]", "string"),
            ("round([revenue_alias_missing_is_fine_in_parse])", None),
        ],
    )
    def test_result_types(self, text: str, expected: str | None) -> None:
        if expected is None:
            with pytest.raises(CalcError, match="no column"):
                kind(text)
            return
        assert kind(text) == expected

    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ("", "Enter a formula"),
            ("[Region] + 1", "needs a number, not text"),
            ("[Revenue] AND [Paid]", "needs true/false"),
            ("[Region] > 3", "Cannot compare text with a whole number"),
            ("IF([Units], 1, 2)", "condition needs true/false"),
            ("IF([Paid], 1, 'x')", "same kind of value"),
            ("YEAR([Region])", "needs a date"),
            ("ROUND()", "takes 1 to 2 values"),
            ("LEFT([Region])", "takes 2 values"),
            ("COALESCE([Units])", "at least 2"),
            ("[Order Date] > '2026-13-01'", "not a real date"),
            ("[Order Date] > 'soon'", "not a date"),
            ("NULL", "always empty"),
            ("[region]", "Did you mean \\[Region\\]"),
            ("[]", "empty"),
            ("Revenue - Cost", "put column names in brackets"),
            ("SLEEP(10)", "Unknown function SLEEP"),
            ("(1 + 2", "Expected '\\)'"),
            ("1 + ", "Expected a value"),
            ("1 2", "Unexpected '2'"),
            ("'unclosed", "closing quote"),
            ("[Unclosed", "closing bracket"),
            ("1 ; DROP TABLE x", "Unexpected character"),
            ("x" * 1001, "at most 1000"),
            ("(" * 60 + "1" + ")" * 60, "nested too deeply"),
            ("-" * 60 + "1", "nested too deeply"),
        ],
    )
    def test_errors(self, text: str, message: str) -> None:
        with pytest.raises(CalcError, match=message):
            kind(text)


class TestSafety:
    def test_text_and_names_never_reach_sql(self) -> None:
        sql, _, params, used = compile_expression(
            "IF([Region] = 'x''); DROP TABLE dataset; --', [Odd \"name\"]]], 'ok')", COLS
        )
        assert "DROP" not in sql and "--" not in sql
        assert "x'); DROP TABLE dataset; --" in params
        assert '"Odd ""name""]"' in sql  # a quoted identifier, quotes doubled
        assert used == {"Region", 'Odd "name"]'}

    def test_tokens_cover_the_input(self) -> None:
        assert [t.kind for t in tokenize("[A] >= 1.5e3 & 'b'")] == [
            "col", "op", "num", "op", "str", "end",
        ]
        assert parse("1 + 2 * 3").args[1].value == "*"  # precedence


class TestFields:
    def test_build_in_order_and_dependencies(self) -> None:
        calcs = build(
            [
                {"name": "Profit", "expression": "[Revenue] - [Cost]"},
                {"name": "  Margin   % ", "expression": "[Profit] / [Revenue]"},
                {"name": "Big", "expression": "[Units] > 100"},
            ],
            COLS,
        )
        assert [(c.name, c.type) for c in calcs] == [
            ("Profit", "float"), ("Margin %", "float"), ("Big", "boolean"),
        ]
        assert [c.name for c in needed(calcs, {"Margin %"})] == ["Profit", "Margin %"]
        assert needed(calcs, {"Region"}) == []

    @pytest.mark.parametrize(
        ("defs", "message"),
        [
            ([{"name": "", "expression": "1"}], "Give the calculated field a name"),
            ([{"name": "revenue", "expression": "1"}], "already a column"),
            ([{"name": "__x", "expression": "1"}], "two underscores"),
            ([{"name": "A", "expression": "[B]"}, {"name": "B", "expression": "1"}], "A: There is no column"),
            ([{"name": "A", "expression": "1"}, {"name": "a", "expression": "2"}], "already"),
            ([{"name": f"F{i}", "expression": "1"} for i in range(MAX_CALCULATIONS + 1)], "at most"),
        ],
    )
    def test_build_rejects(self, defs: list[dict[str, str]], message: str) -> None:
        with pytest.raises(CalcError, match=message):
            build(defs, COLS)

    def test_lenient_build_skips_broken_fields(self) -> None:
        defs = [{"name": "Old", "expression": "[Gone] * 2"}, {"name": "Ok", "expression": "[Units] + 1"}]
        assert [c.name for c in build(defs, COLS, strict=False)] == ["Ok"]


@pytest.fixture
def parquet(tmp_path: Path) -> Path:
    table = pa.table({
        "Revenue": [100.0, 50.0, 80.0, None],
        "Cost": [60.0, 50.0, 0.0, 10.0],
        "Units": [12, 3, 20, 1],
        "Region": ["EU", "US", "EU", None],
        "Order Date": [dt.date(2026, 1, 5), dt.date(2026, 2, 1), dt.date(2025, 12, 31), None],
        "Paid": [True, False, True, None],
    })
    path = tmp_path / "data.parquet"
    pq.write_table(table, path)
    return path


def run(path: Path, spec: QuerySpec, defs: list[dict[str, str]]) -> list[dict[str, object]]:
    types = {k: v for k, v in COLS.items() if not k.startswith("Odd")}
    calcs = build(defs, types)
    plan = QueryCompiler(column_types=types, calculations=calcs).compile(spec)
    assert plan.success, plan.errors
    assert plan.plan is not None
    return list(DuckDBExecutor().execute(plan.plan, path).rows)


def test_executes_in_duckdb(parquet: Path) -> None:
    defs = [
        {"name": "Profit", "expression": "[Revenue] - [Cost]"},
        {"name": "Margin", "expression": "ROUND([Profit] / [Cost] * 100, 1)"},
        {"name": "Size", "expression": "IF([Units] >= 10, 'Bulk', 'Single')"},
        {"name": "Year", "expression": "YEAR([Order Date])"},
        {"name": "Label", "expression": "COALESCE([Region], '?') & ':' & [Units]"},
        {"name": "Recent", "expression": "[Order Date] >= '2026-01-01'"},
    ]
    rows = run(parquet, QuerySpec(columns=["Units", "Profit", "Margin", "Size", "Year", "Label",
                                           "Recent"], limit=10), defs)
    by_units = {r["Units"]: r for r in rows}
    assert by_units[12] == {"Units": 12, "Profit": 40.0, "Margin": 66.7, "Size": "Bulk",
                            "Year": 2026, "Label": "EU:12", "Recent": True}
    assert by_units[20]["Margin"] is None  # division by zero gives an empty value
    assert by_units[1]["Profit"] is None and by_units[1]["Label"] == "?:1"

    grouped = run(parquet, QuerySpec(
        dimensions=["Size"],
        measures=[AggregationSpec(column="Profit", function=AggFunction.SUM)],
        filters=[FilterSpec(column="Year", operator=FilterOp.EQ, value=2026)],
    ), defs)
    assert grouped == [{"Size": "Bulk", "Profit": 40.0}, {"Size": "Single", "Profit": 0.0}]
