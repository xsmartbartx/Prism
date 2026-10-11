"""Query Compiler — pure function from QuerySpec to ExecutionPlan.

Per ADR-0003 D5: The compiler is a pure function producing an immutable,
content-addressed execution plan. It has no side effects.

Phase 0 v0:
- Validates that referenced columns exist in the dataset schema
- Resolves column aliases
- Builds a structured plan (never by string concatenation)
- Injects default limit when absent
- Supports single-dataset queries only (no joins, no semantic model)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from data.query.plan import ExecutionPlan
from data.query.spec import (
    AggregationSpec,
    FilterOp,
    FilterSpec,
    QuerySpec,
    SortSpec,
)


@dataclass(frozen=True)
class CompilationResult:
    """The result of compiling a QuerySpec."""

    success: bool
    plan: ExecutionPlan | None = field(default=None)
    errors: list[str] = field(default_factory=list)

    @property
    def plan_hash(self) -> str | None:
        return self.plan.plan_hash if self.plan else None


_KNOWN_FUNCTIONS = {"sum", "avg", "count", "min", "max"}


class QueryCompiler:
    """Compiles a QuerySpec into an immutable ExecutionPlan.

    The compiler validates:
    - All referenced columns exist in the dataset schema
    - Aggregation functions are known
    - Measure columns are present when group_by columns are specified
    - Filters use valid operators
    """

    def __init__(self, dataset_columns: set[str] | None = None) -> None:
        self._dataset_columns = dataset_columns or set()

    def compile(self, spec: QuerySpec) -> CompilationResult:
        """Compile a QuerySpec into an ExecutionPlan.

        Args:
            spec: The declarative query specification.

        Returns:
            A CompilationResult with the plan or error messages.
        """
        errors: list[str] = []

        # --- Validate dimensions ---
        for dim in spec.dimensions:
            if self._dataset_columns and dim not in self._dataset_columns:
                errors.append(
                    f"Dimension '{dim}' not found in dataset columns. "
                    f"Available: {sorted(self._dataset_columns)}"
                )

        # --- Validate measures ---
        for measure in spec.measures:
            if measure.function.value not in _KNOWN_FUNCTIONS:
                errors.append(
                    f"Unknown aggregation function '{measure.function.value}'. "
                    f"Known: {sorted(_KNOWN_FUNCTIONS)}"
                )
            if self._dataset_columns and measure.column not in self._dataset_columns:
                errors.append(
                    f"Measure column '{measure.column}' not found in dataset columns. "
                    f"Available: {sorted(self._dataset_columns)}"
                )

        # --- Validate filters ---
        for f in spec.filters:
            if self._dataset_columns and f.column not in self._dataset_columns:
                errors.append(
                    f"Filter column '{f.column}' not found in dataset columns. "
                    f"Available: {sorted(self._dataset_columns)}"
                )
            _validate_filter_operator(f, errors)

        # --- Validate sort ---
        for s in spec.sort:
            if self._dataset_columns and s.column not in self._dataset_columns:
                errors.append(
                    f"Sort column '{s.column}' not found in dataset columns. "
                    f"Available: {sorted(self._dataset_columns)}"
                )

        # --- Grain validation ---
        if spec.measures and not spec.dimensions:
            errors.append(
                "Measures require at least one dimension (GROUP BY column). "
                "Use dimensions=[...] to specify the grouping."
            )

        if errors:
            return CompilationResult(success=False, errors=errors)

        # --- Build the select columns ---
        select_columns: list[str] = list(spec.dimensions)
        for m in spec.measures:
            select_columns.append(m.column)

        # --- Resolve limit ---
        limit = spec.limit if spec.limit is not None else 1000

        # --- Build the plan ---
        plan = ExecutionPlan(
            select_columns=tuple(select_columns),
            group_by_columns=tuple(spec.dimensions),
            aggregations=tuple(spec.measures),
            filters=tuple(spec.filters),
            sort=tuple(spec.sort),
            limit=limit,
            offset=spec.offset,
        )

        return CompilationResult(success=True, plan=plan)


def _validate_filter_operator(f: FilterSpec, errors: list[str]) -> None:
    """Validate that a filter's operator can be used with its value type."""
    valid_operators = {op.value for op in FilterOp}
    if f.operator.value not in valid_operators:
        errors.append(
            f"Unknown filter operator '{f.operator.value}'. "
            f"Valid operators: {sorted(valid_operators)}"
        )

    # Type-specific validation
    if f.operator in (FilterOp.GT, FilterOp.GTE, FilterOp.LT, FilterOp.LTE):
        if not isinstance(f.value, (int, float)):
            errors.append(
                f"Filter operator '{f.operator.value}' requires a numeric value, "
                f"got {type(f.value).__name__}"
            )