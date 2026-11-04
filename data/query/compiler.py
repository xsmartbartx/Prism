"""Query Compiler — pure function from QuerySpec to ExecutionPlan.

Per ADR-0003 D5: The compiler is a pure function producing an immutable,
content-addressed execution plan. It has no side effects.

It validates:
- every referenced column exists (when the schema is known);
- aggregation functions suit the column type (no ``sum`` of text);
- filter values are well-typed for their column and operator;
- time grains apply only to date dimensions;
- output column names are unique;
- sorts reference output columns;
- the row limit stays inside the platform ceiling.

Values stay bound parameters end to end; nothing is ever spliced into
query text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from data.query.plan import ExecutionPlan
from data.query.spec import (
    AggFunction,
    FilterOp,
    FilterSpec,
    QuerySpec,
)

DEFAULT_LIMIT = 1000
MAX_IN_VALUES = 1000

_NUMERIC = {"integer", "float"}
_NUMERIC_AGGS = {AggFunction.SUM, AggFunction.AVG, AggFunction.MEDIAN}
_RANGE_OPS = {FilterOp.GT, FilterOp.GTE, FilterOp.LT, FilterOp.LTE}
_TEXT_OPS = {FilterOp.CONTAINS, FilterOp.STARTS_WITH}
_LIST_OPS = {FilterOp.IN, FilterOp.NOT_IN}
_NULL_OPS = {FilterOp.IS_NULL, FilterOp.NOT_NULL}


@dataclass(frozen=True)
class CompilationResult:
    """The result of compiling a QuerySpec."""

    success: bool
    plan: ExecutionPlan | None = field(default=None)
    errors: list[str] = field(default_factory=list)

    @property
    def plan_hash(self) -> str | None:
        return self.plan.plan_hash if self.plan else None


_KNOWN_FUNCTIONS = {f.value for f in AggFunction}


class QueryCompiler:
    """Compiles a QuerySpec into an immutable ExecutionPlan."""

    def __init__(
        self,
        dataset_columns: set[str] | None = None,
        *,
        column_types: dict[str, str] | None = None,
        max_limit: int = 50_000,
    ) -> None:
        self._column_types = dict(column_types or {})
        self._dataset_columns = set(dataset_columns or set()) | set(self._column_types)
        self._max_limit = max_limit

    def _check_column(self, name: str, what: str, errors: list[str]) -> bool:
        if self._dataset_columns and name not in self._dataset_columns:
            errors.append(
                f"{what} '{name}' not found in dataset columns. "
                f"Available: {sorted(self._dataset_columns)}"
            )
            return False
        return True

    def compile(self, spec: QuerySpec) -> CompilationResult:
        errors: list[str] = []
        types = self._column_types

        for dim in spec.dimensions:
            self._check_column(dim, "Dimension", errors)
        if len(set(spec.dimensions)) != len(spec.dimensions):
            errors.append("Dimensions must not repeat")

        for measure in spec.measures:
            if measure.function.value not in _KNOWN_FUNCTIONS:  # pragma: no cover - enum-guarded
                errors.append(f"Unknown aggregation function '{measure.function.value}'")
            if measure.column == "*":
                if measure.function != AggFunction.COUNT:
                    errors.append("Only count may aggregate '*' (all rows)")
                continue
            if not self._check_column(measure.column, "Measure column", errors):
                continue
            col_type = types.get(measure.column)
            if col_type and measure.function in _NUMERIC_AGGS and col_type not in _NUMERIC:
                errors.append(
                    f"Cannot {measure.function.value} '{measure.column}' ({col_type}); "
                    "use count, count_distinct, min or max"
                )

        for f in spec.filters:
            if self._check_column(f.column, "Filter column", errors):
                _validate_filter(f, types.get(f.column), errors)

        for dim, grain in spec.time_grain.items():
            if dim not in spec.dimensions:
                errors.append(
                    f"Time grain '{grain.value}' set for '{dim}', which is not a dimension"
                )
            elif types.get(dim) and types[dim] != "date":
                errors.append(f"Time grain needs a date column; '{dim}' is {types[dim]}")

        raw = not spec.dimensions and not spec.measures
        if raw:
            for col in spec.columns:
                self._check_column(col, "Column", errors)
            outputs = list(spec.columns) or sorted(self._dataset_columns)
        else:
            if spec.columns:
                errors.append("'columns' projects raw rows; it cannot combine with aggregation")
            outputs = list(spec.dimensions) + [m.output_name for m in spec.measures]
        if len(set(outputs)) != len(outputs):
            errors.append(
                "Output column names collide; give repeated measures an alias "
                "(e.g. sum_revenue, avg_revenue)"
            )

        output_set = set(outputs)
        for s in spec.sort:
            if s.column in output_set:
                continue
            if raw and (not self._dataset_columns or s.column in self._dataset_columns):
                continue
            if not self._dataset_columns and not output_set:
                continue
            errors.append(
                f"Sort column '{s.column}' not found in dataset columns or query output. "
                f"Available: {sorted(output_set)}"
            )

        limit = spec.limit if spec.limit is not None else DEFAULT_LIMIT
        if limit > self._max_limit:
            limit = self._max_limit

        if errors:
            return CompilationResult(success=False, errors=errors)

        referenced = (
            set(spec.dimensions)
            | {m.column for m in spec.measures if m.column != "*"}
            | {f.column for f in spec.filters}
            | set(outputs if raw else [])
        )
        plan = ExecutionPlan(
            select_columns=tuple(outputs),
            group_by_columns=tuple(spec.dimensions),
            aggregations=tuple(spec.measures),
            filters=tuple(spec.filters),
            sort=tuple(spec.sort),
            limit=limit,
            offset=spec.offset,
            time_grains=tuple(sorted((d, g.value) for d, g in spec.time_grain.items())),
            column_types=tuple(sorted((c, t) for c, t in types.items() if c in referenced)),
            raw=raw,
        )
        return CompilationResult(success=True, plan=plan)


def coerce_filter_value(value: Any, col_type: str | None) -> Any:
    """Coerce one bound value to the column's Python type (raises ValueError)."""
    if value is None:
        return None
    if col_type == "date":
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value)[:10])
    if col_type == "integer":
        if isinstance(value, bool):
            raise ValueError("boolean is not an integer")
        if isinstance(value, float) and not value.is_integer():
            return value
        return int(value)
    if col_type == "float":
        if isinstance(value, bool):
            raise ValueError("boolean is not a number")
        return float(value)
    if col_type == "boolean":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"true", "1", "yes"}:
            return True
        if text in {"false", "0", "no"}:
            return False
        raise ValueError(f"'{value}' is not a boolean")
    if col_type == "string":
        return str(value)
    return value


def _validate_filter(f: FilterSpec, col_type: str | None, errors: list[str]) -> None:
    op = f.operator
    label = f"Filter on '{f.column}'"
    if op in _NULL_OPS:
        return
    if op in _LIST_OPS:
        if not isinstance(f.value, list) or not f.value:
            errors.append(f"{label}: '{op.value}' needs a non-empty list of values")
            return
        if len(f.value) > MAX_IN_VALUES:
            errors.append(f"{label}: at most {MAX_IN_VALUES} values are allowed")
            return
        values = f.value
    elif op == FilterOp.BETWEEN:
        if not isinstance(f.value, list) or len(f.value) != 2:
            errors.append(f"{label}: 'between' needs [low, high]")
            return
        values = f.value
    elif op in _TEXT_OPS:
        if not isinstance(f.value, str) or not f.value:
            errors.append(f"{label}: '{op.value}' needs a text value")
            return
        if col_type and col_type != "string":
            errors.append(f"{label}: '{op.value}' only applies to text columns")
        return
    else:
        values = [f.value]

    if op in _RANGE_OPS or op == FilterOp.BETWEEN:
        if col_type is None:
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
                errors.append(
                    f"Filter operator '{op.value}' requires a numeric value, "
                    f"got {type(values[0]).__name__}"
                )
            return
        if col_type == "boolean":
            errors.append(f"{label}: '{op.value}' cannot compare booleans")
            return

    if col_type is None:
        return
    for v in values:
        try:
            coerce_filter_value(v, col_type)
        except (TypeError, ValueError):
            errors.append(f"{label}: '{v}' is not a valid {col_type}")
            return
