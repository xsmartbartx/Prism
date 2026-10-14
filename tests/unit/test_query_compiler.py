"""Tests for the Query Compiler — validation, resolution, plan construction."""
from __future__ import annotations

import pytest

from data.query.compiler import QueryCompiler
from data.query.spec import (
    AggFunction,
    AggregationSpec,
    FilterOp,
    FilterSpec,
    QuerySpec,
    SortDir,
    SortSpec,
)


class TestCompilerValidation:
    """Tests for compiler validation — errors for invalid specs."""

    def setup_method(self) -> None:
        self.dataset_columns = {"name", "age", "salary", "department", "hire_date"}
        self.compiler = QueryCompiler(dataset_columns=self.dataset_columns)

    def test_compiles_valid_spec(self) -> None:
        spec = QuerySpec(
            dimensions=["department"],
            measures=[AggregationSpec(column="salary", function=AggFunction.SUM)],
            sort=[SortSpec(column="department", direction=SortDir.ASC)],
        )
        result = self.compiler.compile(spec)
        assert result.success
        assert result.plan is not None
        assert result.plan.plan_hash is not None

    def test_compiles_no_grouping(self) -> None:
        """No dimensions, no measures -> simple projection."""
        spec = QuerySpec(dimensions=["name", "age"], limit=10)
        result = self.compiler.compile(spec)
        assert result.success
        assert result.plan is not None

    def test_rejects_unknown_dimension(self) -> None:
        spec = QuerySpec(dimensions=["nonexistent"])
        result = self.compiler.compile(spec)
        assert not result.success
        assert any("nonexistent" in err for err in result.errors)

    def test_rejects_unknown_measure_column(self) -> None:
        spec = QuerySpec(
            dimensions=["department"],
            measures=[AggregationSpec(column="fake_col", function=AggFunction.SUM)],
        )
        result = self.compiler.compile(spec)
        assert not result.success
        assert any("fake_col" in err for err in result.errors)

    def test_rejects_unknown_aggregation_function(self) -> None:
        """Pydantic validates enum at construction — expect ValidationError."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            _ = AggregationSpec(column="salary", function="bogus")  # type: ignore

    def test_rejects_measures_without_dimensions(self) -> None:
        spec = QuerySpec(
            measures=[AggregationSpec(column="salary", function=AggFunction.SUM)],
        )
        result = self.compiler.compile(spec)
        assert not result.success
        assert any("dimension" in err.lower() for err in result.errors)

    def test_rejects_unknown_filter_column(self) -> None:
        spec = QuerySpec(
            filters=[FilterSpec(column="ghost", operator=FilterOp.EQ, value=42)],
        )
        result = self.compiler.compile(spec)
        assert not result.success
        assert any("ghost" in err for err in result.errors)

    def test_rejects_unknown_sort_column(self) -> None:
        spec = QuerySpec(
            sort=[SortSpec(column="phanton", direction=SortDir.ASC)],
        )
        result = self.compiler.compile(spec)
        assert not result.success
        assert any("phanton" in err for err in result.errors)

    def test_rejects_comparison_filter_on_non_numeric(self) -> None:
        spec = QuerySpec(
            filters=[FilterSpec(column="name", operator=FilterOp.GT, value="hello")],
        )
        result = self.compiler.compile(spec)
        assert not result.success
        assert any("numeric" in err.lower() for err in result.errors)
class TestCompilerPlanConstruction:
    """Tests for correct plan construction."""

    def setup_method(self) -> None:
        self.dataset_columns = {"name", "age", "salary", "department", "hire_date"}
        self.compiler = QueryCompiler(dataset_columns=self.dataset_columns)

    def test_injects_default_limit(self) -> None:
        """Compiler injects default limit of 1000 when absent."""
        spec = QuerySpec(dimensions=["name"])
        result = self.compiler.compile(spec)
        assert result.success
        assert result.plan is not None
        assert result.plan.limit == 1000

    def test_preserves_explicit_limit(self) -> None:
        spec = QuerySpec(dimensions=["name"], limit=50)
        result = self.compiler.compile(spec)
        assert result.success
        assert result.plan is not None
        assert result.plan.limit == 50

    def test_plan_has_stable_hash(self) -> None:
        """Same spec produces same hash."""
        spec1 = QuerySpec(
            dimensions=["department"],
            measures=[AggregationSpec(column="salary", function=AggFunction.SUM)],
        )
        spec2 = QuerySpec(
            dimensions=["department"],
            measures=[AggregationSpec(column="salary", function=AggFunction.SUM)],
        )
        result1 = self.compiler.compile(spec1)
        result2 = self.compiler.compile(spec2)
        assert result1.success and result2.success
        assert result1.plan_hash == result2.plan_hash

    def test_different_spec_different_hash(self) -> None:
        """Different specs produce different hashes."""
        spec1 = QuerySpec(
            dimensions=["department"],
            measures=[AggregationSpec(column="salary", function=AggFunction.SUM)],
        )
        spec2 = QuerySpec(
            dimensions=["department"],
            measures=[AggregationSpec(column="salary", function=AggFunction.AVG)],
        )
        result1 = self.compiler.compile(spec1)
        result2 = self.compiler.compile(spec2)
        assert result1.success and result2.success
        assert result1.plan_hash != result2.plan_hash

    def test_select_columns_includes_dimensions_and_measures(self) -> None:
        spec = QuerySpec(
            dimensions=["department"],
            measures=[AggregationSpec(column="salary", function=AggFunction.SUM)],
        )
        result = self.compiler.compile(spec)
        assert result.success
        assert result.plan is not None
        assert "department" in result.plan.select_columns
        assert "salary" in result.plan.select_columns

    def test_compiler_no_dataset_columns(self) -> None:
        """Compiler works without dataset columns (runtime validation only)."""
        compiler = QueryCompiler(dataset_columns=None)  # type: ignore
        spec = QuerySpec(
            dimensions=["department"],
            measures=[AggregationSpec(column="salary", function=AggFunction.SUM)],
        )
        result = compiler.compile(spec)
        assert result.success
        assert result.plan is not None