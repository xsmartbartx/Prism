"""DuckDB engine profile — executes ExecutionPlans over Parquet dataset versions.

The plan is translated into a single SQL statement whose identifiers are
validated, double-quoted names and whose every value is a bound
parameter. The connection is sandboxed per query: the dataset is handed
in as an Arrow dataset, then DuckDB's own file/network access is disabled
and the configuration locked before the generated SQL runs.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.dataset as pads

from core.errors import PrismError
from data.query.compiler import coerce_filter_value
from data.query.plan import ExecutionPlan, ResultSet
from data.query.spec import AggFunction, FilterOp, SortDir

_AGG_SQL = {
    AggFunction.SUM: "SUM({})",
    AggFunction.AVG: "AVG({})",
    AggFunction.COUNT: "COUNT({})",
    AggFunction.MIN: "MIN({})",
    AggFunction.MAX: "MAX({})",
    AggFunction.COUNT_DISTINCT: "COUNT(DISTINCT {})",
    AggFunction.MEDIAN: "MEDIAN({})",
}
_CMP_SQL = {
    FilterOp.EQ: "=",
    FilterOp.NE: "<>",
    FilterOp.GT: ">",
    FilterOp.GTE: ">=",
    FilterOp.LT: "<",
    FilterOp.LTE: "<=",
}
_GRAINS = {"day", "week", "month", "quarter", "year"}


class QueryTimeout(PrismError):
    """The query exceeded its time budget and was cancelled."""


def quote_ident(name: str) -> str:
    """Quote an identifier for DuckDB. Names come from the validated schema."""
    if "\x00" in name:
        raise ValueError("Identifier contains NUL")
    return '"' + name.replace('"', '""') + '"'


def plan_to_sql(plan: ExecutionPlan, relation: str = "dataset") -> tuple[str, list[Any]]:
    """Translate a plan into ``(sql, params)``. Pure; no I/O."""
    types = dict(plan.column_types)
    grains = dict(plan.time_grains)
    params: list[Any] = []

    def dim_expr(col: str) -> str:
        grain = grains.get(col)
        if grain:
            if grain not in _GRAINS:
                raise ValueError(f"Unknown grain {grain}")
            return f"CAST(date_trunc('{grain}', {quote_ident(col)}) AS DATE)"
        return quote_ident(col)

    select: list[str] = []
    if plan.raw:
        select = [quote_ident(c) for c in plan.select_columns] or ["*"]
    else:
        select += [f"{dim_expr(d)} AS {quote_ident(d)}" for d in plan.group_by_columns]
        for agg in plan.aggregations:
            arg = "*" if agg.column == "*" else quote_ident(agg.column)
            select.append(f"{_AGG_SQL[agg.function].format(arg)} AS {quote_ident(agg.output_name)}")

    where: list[str] = []
    for f in plan.filters:
        col = quote_ident(f.column)
        t = types.get(f.column)

        def bind(v: Any, _t: str | None = t) -> str:
            params.append(coerce_filter_value(v, _t) if _t else v)
            return "?"

        op = f.operator
        if op == FilterOp.IS_NULL:
            where.append(f"{col} IS NULL")
        elif op == FilterOp.NOT_NULL:
            where.append(f"{col} IS NOT NULL")
        elif op in (FilterOp.IN, FilterOp.NOT_IN):
            marks = ", ".join(bind(v) for v in f.value)
            neg = "NOT " if op == FilterOp.NOT_IN else ""
            where.append(f"{col} {neg}IN ({marks})")
        elif op == FilterOp.BETWEEN:
            low, high = bind(f.value[0]), bind(f.value[1])
            where.append(f"{col} BETWEEN {low} AND {high}")
        elif op == FilterOp.CONTAINS:
            params.append(str(f.value))
            where.append(f"contains(lower({col}), lower(?))")
        elif op == FilterOp.STARTS_WITH:
            params.append(str(f.value))
            where.append(f"starts_with(lower({col}), lower(?))")
        else:
            where.append(f"{col} {_CMP_SQL[op]} {bind(f.value)}")

    sql = f"SELECT {', '.join(select)}, COUNT(*) OVER () AS __prism_total FROM {relation}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    if plan.group_by_columns and not plan.raw:
        sql += " GROUP BY " + ", ".join(str(i + 1) for i in range(len(plan.group_by_columns)))
    if plan.sort:
        parts = []
        for s in plan.sort:
            direction = "DESC" if s.direction == SortDir.DESC else "ASC"
            parts.append(f"{quote_ident(s.column)} {direction} NULLS LAST")
        sql += " ORDER BY " + ", ".join(parts)
    elif plan.group_by_columns and not plan.raw:
        sql += " ORDER BY " + ", ".join(
            f"{i + 1} ASC NULLS LAST" for i in range(len(plan.group_by_columns))
        )
    if plan.limit is not None:
        sql += f" LIMIT {int(plan.limit)}"
    if plan.offset:
        sql += f" OFFSET {int(plan.offset)}"
    return sql, params


class DuckDBExecutor:
    """Runs plans against one Parquet file with a hard time budget."""

    def __init__(
        self, *, timeout_s: float = 30.0, memory_limit: str = "1GB", threads: int = 4
    ) -> None:
        self.timeout_s = timeout_s
        self.memory_limit = memory_limit
        self.threads = threads

    def _connect(self, parquet_path: Path) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect(database=":memory:")
        con.execute(f"SET memory_limit='{self.memory_limit}'")
        con.execute(f"SET threads={int(self.threads)}")
        con.register("dataset", pads.dataset(str(parquet_path), format="parquet"))
        con.execute("SET enable_external_access=false")
        con.execute("SET lock_configuration=true")
        return con

    def execute(self, plan: ExecutionPlan, parquet_path: Path | str) -> ResultSet:
        sql, params = plan_to_sql(plan)
        con = self._connect(Path(parquet_path))
        timer = threading.Timer(self.timeout_s, con.interrupt)
        timer.start()
        try:
            table = con.sql(sql, params=params).to_arrow_table()
        except duckdb.InterruptException as exc:
            raise QueryTimeout(f"Query exceeded {self.timeout_s:.0f}s and was cancelled") from exc
        except duckdb.Error as exc:
            raise PrismError(f"Query failed: {exc}", code="QueryError") from exc
        finally:
            timer.cancel()
            con.close()
        total = table.column("__prism_total")[0].as_py() if table.num_rows else 0
        if not table.num_rows and plan.offset:
            total = self.count(plan, parquet_path)
        rows = table.drop_columns(["__prism_total"]).to_pylist()
        columns = tuple(table.column_names[:-1])
        return ResultSet(
            columns=columns, rows=tuple(rows), row_count=total, plan_hash=plan.plan_hash
        )

    def count(self, plan: ExecutionPlan, parquet_path: Path | str) -> int:
        """Total result rows ignoring limit/offset (used for past-the-end pages)."""
        from dataclasses import replace

        inner, params = plan_to_sql(replace(plan, limit=None, offset=0, sort=()))
        con = self._connect(Path(parquet_path))
        try:
            row = con.execute(f"SELECT COUNT(*) FROM ({inner})", params).fetchone()
        finally:
            con.close()
        return int(row[0]) if row else 0
