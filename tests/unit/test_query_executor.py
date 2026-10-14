"""Tests for the Query Executor — filtering, grouping, aggregation, sorting."""
from __future__ import annotations

from data.query.executor import QueryExecutor
from data.query.plan import ExecutionPlan
from data.query.spec import (
    AggFunction,
    AggregationSpec,
    FilterOp,
    FilterSpec,
    SortDir,
    SortSpec,
)


ROWS = [
    {"name": "Alice", "age": 30, "salary": 70000, "department": "Engineering"},
    {"name": "Bob", "age": 25, "salary": 60000, "department": "Engineering"},
    {"name": "Charlie", "age": 35, "salary": 80000, "department": "Marketing"},
    {"name": "Diana", "age": 30, "salary": 65000, "department": "Marketing"},
    {"name": "Eve", "age": 28, "salary": 55000, "department": "Engineering"},
]


class TestFiltering:
    """Tests for row filtering."""

    def setup_method(self) -> None:
        self.executor = QueryExecutor()

    def test_filter_eq(self) -> None:
        plan = ExecutionPlan(
            select_columns=("name",),
            filters=(FilterSpec(column="name", operator=FilterOp.EQ, value="Alice"),),
        )
        result = self.executor.execute(plan, ROWS)
        assert result.row_count == 1
        assert result.rows[0]["name"] == "Alice"

    def test_filter_ne(self) -> None:
        plan = ExecutionPlan(
            select_columns=("name",),
            filters=(FilterSpec(column="name", operator=FilterOp.NE, value="Alice"),),
        )
        result = self.executor.execute(plan, ROWS)
        assert result.row_count == 4
        assert all(r["name"] != "Alice" for r in result.rows)

    def test_filter_gt(self) -> None:
        plan = ExecutionPlan(
            select_columns=("name",),
            filters=(FilterSpec(column="age", operator=FilterOp.GT, value=30),),
        )
        result = self.executor.execute(plan, ROWS)
        assert result.row_count == 1
        assert result.rows[0]["name"] == "Charlie"

    def test_filter_gte(self) -> None:
        plan = ExecutionPlan(
            select_columns=("name",),
            filters=(FilterSpec(column="age", operator=FilterOp.GTE, value=30),),
        )
        result = self.executor.execute(plan, ROWS)
        assert result.row_count == 3

    def test_filter_lt(self) -> None:
        plan = ExecutionPlan(
            select_columns=("name",),
            filters=(FilterSpec(column="age", operator=FilterOp.LT, value=30),),
        )
        result = self.executor.execute(plan, ROWS)
        # Bob (25) and Eve (28) are both < 30
        assert result.row_count == 2
        names = {r["name"] for r in result.rows}
        assert "Bob" in names
        assert "Eve" in names

    def test_filter_lte(self) -> None:
        plan = ExecutionPlan(
            select_columns=("name",),
            filters=(FilterSpec(column="age", operator=FilterOp.LTE, value=28),),
        )
        result = self.executor.execute(plan, ROWS)
        # Bob (25) and Eve (28) are both <= 28
        assert result.row_count == 2

    def test_multiple_filters(self) -> None:
        """All filters must match (AND logic)."""
        plan = ExecutionPlan(
            select_columns=("name",),
            filters=(
                FilterSpec(column="department", operator=FilterOp.EQ, value="Engineering"),
                FilterSpec(column="age", operator=FilterOp.GT, value=28),
            ),
        )
        result = self.executor.execute(plan, ROWS)
        assert result.row_count == 1  # Alice (30, Engineering)
        assert result.rows[0]["name"] == "Alice"

    def test_no_filters_returns_all(self) -> None:
        plan = ExecutionPlan(select_columns=("name",))
        result = self.executor.execute(plan, ROWS)
        assert result.row_count == 5
class TestAggregation:
    """Tests for aggregation with GROUP BY."""

    def setup_method(self) -> None:
        self.executor = QueryExecutor()

    def test_sum_by_department(self) -> None:
        plan = ExecutionPlan(
            select_columns=("department", "salary"),
            group_by_columns=("department",),
            aggregations=(AggregationSpec(column="salary", function=AggFunction.SUM),),
        )
        result = self.executor.execute(plan, ROWS)
        assert result.row_count == 2
        by_dept = {r["department"]: r["salary"] for r in result.rows}
        assert by_dept["Engineering"] == 70000 + 60000 + 55000
        assert by_dept["Marketing"] == 80000 + 65000

    def test_count_by_department(self) -> None:
        plan = ExecutionPlan(
            select_columns=("department", "salary"),
            group_by_columns=("department",),
            aggregations=(AggregationSpec(column="name", function=AggFunction.COUNT),),
        )
        result = self.executor.execute(plan, ROWS)
        by_dept = {r["department"]: r["name"] for r in result.rows}
        assert by_dept["Engineering"] == 3
        assert by_dept["Marketing"] == 2

    def test_avg_by_department(self) -> None:
        plan = ExecutionPlan(
            select_columns=("department", "salary"),
            group_by_columns=("department",),
            aggregations=(AggregationSpec(column="salary", function=AggFunction.AVG),),
        )
        result = self.executor.execute(plan, ROWS)
        by_dept = {r["department"]: r["salary"] for r in result.rows}
        assert by_dept["Engineering"] == 61666.666666666664  # (70000+60000+55000)/3
        assert by_dept["Marketing"] == 72500  # (80000+65000)/2

    def test_min_and_max(self) -> None:
        """MIN and MAX work on separate columns."""
        plan = ExecutionPlan(
            select_columns=("department", "age", "salary"),
            group_by_columns=("department",),
            aggregations=(
                AggregationSpec(column="age", function=AggFunction.MIN),
                AggregationSpec(column="salary", function=AggFunction.MAX),
            ),
        )
        result = self.executor.execute(plan, ROWS)
        by_dept: dict[str, dict] = {}
        for r in result.rows:
            by_dept[r["department"]] = r
        assert by_dept["Engineering"]["age"] == 25  # MIN age in Engineering
        assert by_dept["Engineering"]["salary"] == 70000  # MAX salary in Engineering
        assert by_dept["Marketing"]["age"] == 30  # MIN age in Marketing (Diana)
        assert by_dept["Marketing"]["salary"] == 80000  # MAX salary in Marketing


class TestSort:
    """Tests for sorting."""

    def setup_method(self) -> None:
        self.executor = QueryExecutor()

    def test_sort_asc(self) -> None:
        plan = ExecutionPlan(
            select_columns=("name",),
            sort=(SortSpec(column="name", direction=SortDir.ASC),),
        )
        result = self.executor.execute(plan, ROWS)
        names = [r["name"] for r in result.rows]
        assert names == sorted(["Alice", "Bob", "Charlie", "Diana", "Eve"])

    def test_sort_desc(self) -> None:
        plan = ExecutionPlan(
            select_columns=("name",),
            sort=(SortSpec(column="name", direction=SortDir.DESC),),
        )
        result = self.executor.execute(plan, ROWS)
        names = [r["name"] for r in result.rows]
        assert names == sorted(
            ["Alice", "Bob", "Charlie", "Diana", "Eve"], reverse=True
        )


class TestLimitAndOffset:
    """Tests for limit and offset."""

    def setup_method(self) -> None:
        self.executor = QueryExecutor()

    def test_limit(self) -> None:
        plan = ExecutionPlan(select_columns=("name",), limit=2)
        result = self.executor.execute(plan, ROWS)
        assert len(result.rows) == 2
        assert result.row_count == 5  # Unfiltered count

    def test_offset(self) -> None:
        plan = ExecutionPlan(select_columns=("name",), offset=3)
        result = self.executor.execute(plan, ROWS)
        assert len(result.rows) == 2
        assert result.rows[0]["name"] == "Diana"

    def test_limit_and_offset(self) -> None:
        plan = ExecutionPlan(
            sort=(SortSpec(column="name", direction=SortDir.ASC),),
            select_columns=("name",),
            limit=2,
            offset=1,
        )
        result = self.executor.execute(plan, ROWS)
        names = [r["name"] for r in result.rows]
        assert names == ["Bob", "Charlie"]  # After Alice at offset 0