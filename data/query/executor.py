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