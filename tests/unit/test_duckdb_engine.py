"""DuckDB engine: SQL generation safety and parity with the reference executor."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pytest

from data.load.store import DatasetStore, arrow_schema
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
from data.query.duck import DuckDBExecutor, plan_to_sql, quote_ident
from tests.unit.test_query_typed import ROWS, TYPES


@pytest.fixture(scope="module")
def parquet(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("store")
    schema = arrow_schema(list(TYPES.items()))
    table = pa.Table.from_pylist(ROWS, schema=schema)
    return DatasetStore(root).write(table, "ws", "ds", 1).path


SPECS = [
    QuerySpec(dimensions=["region"], measures=[AggregationSpec(column="amount", function=AggFunction.SUM)], sort=[SortSpec(column="region")]),
    QuerySpec(dimensions=["day"], time_grain={"day": TimeGrain.MONTH}, measures=[AggregationSpec(column="*", function=AggFunction.COUNT)], sort=[SortSpec(column="day")]),
    QuerySpec(dimensions=["day"], time_grain={"day": TimeGrain.QUARTER}, measures=[AggregationSpec(column="units", function=AggFunction.MAX)], sort=[SortSpec(column="day")]),
    QuerySpec(measures=[AggregationSpec(column="units", function=AggFunction.SUM), AggregationSpec(column="amount", function=AggFunction.AVG)]),
    QuerySpec(columns=["region", "units"], filters=[FilterSpec(column="units", operator=FilterOp.BETWEEN, value=[2, 7])], sort=[SortSpec(column="units", direction=SortDir.DESC)]),
    QuerySpec(columns=["region"], filters=[FilterSpec(column="day", operator=FilterOp.LT, value="2026-02-01")], sort=[SortSpec(column="day")]),
    QuerySpec(columns=["region"], filters=[FilterSpec(column="region", operator=FilterOp.NOT_IN, value=["EU"])], sort=[SortSpec(column="region")]),
    QuerySpec(columns=["region"], filters=[FilterSpec(column="ok", operator=FilterOp.EQ, value=True), FilterSpec(column="region", operator=FilterOp.STARTS_WITH, value="a")]),
    QuerySpec(dimensions=["region"], measures=[AggregationSpec(column="units", function=AggFunction.SUM, alias="u")], sort=[SortSpec(column="u", direction=SortDir.DESC)], limit=2),
]


@pytest.mark.parametrize("spec", SPECS)
def test_parity_with_reference_executor(spec: QuerySpec, parquet: Path) -> None:
    plan = QueryCompiler(column_types=TYPES).compile(spec).plan
    assert plan is not None
    expected = QueryExecutor().execute(plan, ROWS)
    got = DuckDBExecutor().execute(plan, parquet)
    assert list(got.rows) == list(expected.rows)
    assert got.row_count == expected.row_count


def test_total_ignores_limit(parquet: Path) -> None:
    plan = QueryCompiler(column_types=TYPES).compile(QuerySpec(columns=["region"], limit=1)).plan
    assert plan is not None
    res = DuckDBExecutor().execute(plan, parquet)
    assert len(res.rows) == 1 and res.row_count == 4 and res.truncated
    off = QueryCompiler(column_types=TYPES).compile(QuerySpec(columns=["region"], offset=10)).plan
    assert off is not None
    assert DuckDBExecutor().execute(off, parquet).row_count == 4


def test_values_are_bound_never_inlined() -> None:
    evil = "x'); DROP TABLE dataset; --"
    plan = QueryCompiler(column_types=TYPES).compile(
        QuerySpec(columns=["region"], filters=[FilterSpec(column="region", operator=FilterOp.EQ, value=evil)])
    ).plan
    assert plan is not None
    sql, params = plan_to_sql(plan)
    assert evil not in sql and params == [evil]


def test_identifier_quoting() -> None:
    assert quote_ident('we"ird') == '"we""ird"'
    with pytest.raises(ValueError):
        quote_ident("a\x00b")


def test_weird_column_names_roundtrip(tmp_path: Path) -> None:
    name = 'Revenue "EUR"; drop'
    table = pa.Table.from_pylist([{name: 1.5}, {name: 2.0}], schema=arrow_schema([(name, "float")]))
    path = DatasetStore(tmp_path).write(table, "ws", "ds", 1).path
    plan = QueryCompiler(column_types={name: "float"}).compile(
        QuerySpec(measures=[AggregationSpec(column=name, function=AggFunction.SUM, alias="total")])
    ).plan
    assert plan is not None
    assert DuckDBExecutor().execute(plan, path).rows == ({"total": 3.5},)


def test_external_access_is_disabled(parquet: Path) -> None:
    con = DuckDBExecutor()._connect(parquet)
    try:
        with pytest.raises(Exception, match=r"(?i)disabled|permission|external"):
            con.execute("SELECT * FROM read_csv('/etc/hosts')").fetchall()
    finally:
        con.close()
