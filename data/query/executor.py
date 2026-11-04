"""Query Executor — runs an ExecutionPlan against in-memory data.

Phase 0 v0:
- Operates on list[dict] (rows as dicts keyed by column name)
- Pure function: (plan, data) → ResultSet
- Performs: filter → group → aggregate → sort → limit/offset

The executor is a pure function with no side effects. It cannot alter
the plan or escalate a budget.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from data.query.plan import ExecutionPlan, ResultSet
from data.query.spec import AggFunction, AggregationSpec, FilterOp, FilterSpec, SortDir, SortSpec


class QueryExecutor:
    """Executes an ExecutionPlan against a list of dict rows.

    Phase 0 v0 runs entirely in-memory. Future versions may delegate
    to DuckDB, a local analytical engine, or pushdown to live sources.
    """

    def execute(
        self,
        plan: ExecutionPlan,
        rows: list[dict[str, Any]],
    ) -> ResultSet:
        """Execute a compiled plan against a dataset.

        Args:
            plan: The immutable execution plan.
            rows: Dataset rows as dicts keyed by column name.

        Returns:
            A ResultSet with the query results.
        """
        # 1. Filter
        filtered = _filter_rows(rows, list(plan.filters))

        # 2. Group + Aggregate (or just project if no grouping)
        if plan.group_by_columns:
            aggregated = _aggregate(
                filtered,
                list(plan.group_by_columns),
                list(plan.aggregations),
            )
            result_rows: list[dict[str, Any]] = list(aggregated)
        else:
            result_rows = [
                {col: row[col] for col in plan.select_columns if col in row}
                for row in filtered
            ]

        # 3. Sort
        sorted_rows = _sort_rows(result_rows, list(plan.sort))

        # 4. Record total before limit/offset
        total_before = len(sorted_rows)

        # 5. Offset
        if plan.offset > 0:
            sorted_rows = sorted_rows[plan.offset:]

        # 6. Limit
        if plan.limit is not None:
            sorted_rows = sorted_rows[: plan.limit]

        # 7. Build result
        result = ResultSet(
            columns=tuple(plan.select_columns),
            rows=tuple(sorted_rows),
            row_count=total_before,
            plan_hash=plan.plan_hash,
        )
        return result
# ------------------------------------------------------------------
# Pure function helpers (module-level for testability)
# ------------------------------------------------------------------


def _filter_rows(
    rows: list[dict[str, Any]],
    filters: list[FilterSpec],
) -> list[dict[str, Any]]:
    """Apply filter predicates to rows."""
    if not filters:
        return rows

    result: list[dict[str, Any]] = []
    for row in rows:
        include = True
        for f in filters:
            value = row.get(f.column)
            if not _matches_filter(value, f.operator, f.value):
                include = False
                break
        if include:
            result.append(row)
    return result


def _aggregate(
    rows: list[dict[str, Any]],
    group_by_columns: list[str],
    aggregations: list[AggregationSpec],
) -> list[dict[str, Any]]:
    """Group rows and apply aggregation functions."""
    if not rows:
        return []

    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = tuple(row.get(col) for col in group_by_columns)
        groups[key].append(row)

    result: list[dict[str, Any]] = []
    for key, group_rows in groups.items():
        result_row: dict[str, Any] = {}
        for i, col in enumerate(group_by_columns):
            result_row[col] = key[i]

        for agg in aggregations:
            values = [
                row.get(agg.column)
                for row in group_rows
                if row.get(agg.column) is not None
            ]
            result_row[agg.column] = _apply_aggregation(values, agg.function)

        result.append(result_row)

    return result


def _sort_rows(
    rows: list[dict[str, Any]],
    sort_specs: list[SortSpec],
) -> list[dict[str, Any]]:
    """Sort rows by the specified columns and directions.

    Uses successive stable sorts (last key first) so mixed ASC/DESC
    composite sorts are exact. ``None`` always sorts last, regardless
    of direction.
    """
    if not sort_specs:
        return rows

    result = list(rows)
    for spec in reversed(sort_specs):
        present = [r for r in result if r.get(spec.column) is not None]
        missing = [r for r in result if r.get(spec.column) is None]
        present.sort(
            key=lambda r, c=spec.column: _sort_value(r.get(c)),  # type: ignore[misc]
            reverse=spec.direction == SortDir.DESC,
        )
        result = present + missing
    return result


# ------------------------------------------------------------------
# Low-level pure functions
# ------------------------------------------------------------------


def _matches_filter(
    value: Any,
    operator: FilterOp,
    target: Any,
) -> bool:
    """Check if a value matches a filter predicate."""
    if operator == FilterOp.EQ:
        return bool(value == target)
    elif operator == FilterOp.NE:
        return bool(value != target)
    elif operator == FilterOp.GT:
        return value is not None and target is not None and bool(value > target)
    elif operator == FilterOp.GTE:
        return value is not None and target is not None and bool(value >= target)
    elif operator == FilterOp.LT:
        return value is not None and target is not None and bool(value < target)
    elif operator == FilterOp.LTE:
        return value is not None and target is not None and bool(value <= target)
    return True


def _apply_aggregation(
    values: list[Any],
    function: AggFunction,
) -> Any:
    """Apply an aggregation function to a list of non-None values."""
    if not values:
        return None

    if function == AggFunction.COUNT:
        return len(values)
    elif function == AggFunction.SUM:
        numeric = [v for v in values if isinstance(v, (int, float))]
        return sum(numeric) if numeric else None
    elif function == AggFunction.AVG:
        numeric = [v for v in values if isinstance(v, (int, float))]
        return sum(numeric) / len(numeric) if numeric else None
    elif function == AggFunction.MIN:
        return min(values)
    elif function == AggFunction.MAX:
        return max(values)
    return None


def _sort_value(value: Any) -> tuple[int, Any]:
    """Map a value onto a totally ordered key, ranking mixed types stably."""
    if isinstance(value, bool):
        return (0, int(value))
    if isinstance(value, (int, float)):
        return (1, value)
    if isinstance(value, str):
        return (3, value)
    return (2, value)
