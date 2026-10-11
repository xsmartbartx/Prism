"""Execution Plan — immutable, content-addressed plan produced by the compiler.

The plan is the compiled form of a QuerySpec. It is:
- Immutable (frozen dataclass)
- Self-contained (no references to source schemas)
- Content-addressed (stable hash for caching)
- Engine-independent (can run against any compatible data source)

Phase 0 v0: In-memory execution against list[dict].
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from data.query.spec import AggregationSpec, FilterSpec, SortSpec


def _stable_hash(obj: Any) -> str:
    """Compute a stable SHA-256 hash of a JSON-serializable object.

    Keys are sorted for reproducibility. This is the identity hash used
    for result caching and plan comparison.
    """
    raw = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ExecutionPlan:
    """An immutable, content-addressed query execution plan.

    Produced by the QueryCompiler. Consumed by the QueryExecutor.
    The plan_hash is the identity used for caching and audit.
    """

    select_columns: tuple[str, ...] = field(default=())
    """Columns to include in the result (projection)."""

    group_by_columns: tuple[str, ...] = field(default=())
    """Columns to group by for aggregation."""

    aggregations: tuple[AggregationSpec, ...] = field(default=())
    """Aggregation specifications (column + function)."""

    filters: tuple[FilterSpec, ...] = field(default=())
    """Filter predicates to apply before aggregation."""

    sort: tuple[SortSpec, ...] = field(default=())
    """Sort directives to apply after aggregation."""

    limit: int | None = field(default=None)
    """Maximum rows to return."""

    offset: int = field(default=0)
    """Rows to skip before returning."""

    plan_hash: str = field(init=False)
    """Stable content address for caching and audit."""

    def __post_init__(self) -> None:
        """Compute the stable hash after all fields are set."""
        plan_dict = {
            "select_columns": list(self.select_columns),
            "group_by_columns": list(self.group_by_columns),
            "aggregations": [
                {"column": a.column, "function": a.function.value}
                for a in self.aggregations
            ],
            "filters": [
                {
                    "column": f.column,
                    "operator": f.operator.value,
                    "value": f.value,
                }
                for f in self.filters
            ],
            "sort": [
                {"column": s.column, "direction": s.direction.value}
                for s in self.sort
            ],
            "limit": self.limit,
            "offset": self.offset,
        }
        # Use object.__setattr__ because frozen=True
        object.__setattr__(self, "plan_hash", _stable_hash(plan_dict))


@dataclass(frozen=True)
class ResultSet:
    """The result of executing a query plan.

    Contains the data rows, column metadata, and execution statistics.
    """

    columns: tuple[str, ...]
    """Column names in the result."""

    rows: tuple[dict[str, Any], ...]
    """Data rows as dicts keyed by column name."""

    row_count: int
    """Total rows before limit/offset (for pagination awareness)."""

    plan_hash: str
    """The plan hash that produced this result (for lineage)."""

    @property
    def column_count(self) -> int:
        return len(self.columns)

    def to_dicts(self) -> list[dict[str, Any]]:
        """Convert rows to a list of dicts (for JSON serialization)."""
        return list(self.rows)