"""Query layer — Query Spec, Compiler, Executor, and Result Cache.

Phase 0 v0:
- Single-dataset queries only (no joins)
- GROUP BY with aggregations (sum, avg, count, min, max)
- Filters (eq, ne, gt, gte, lt, lte)
- Sort (asc, desc)
- Limit / offset
"""

from data.query.compiler import CompilationResult, QueryCompiler
from data.query.executor import QueryExecutor
from data.query.plan import ExecutionPlan, ResultSet
from data.query.spec import (
    AggFunction,
    AggregationSpec,
    FilterOp,
    FilterSpec,
    QuerySpec,
    SortDir,
    SortSpec,
    TimeGrain,
)

__all__ = [
    "AggFunction",
    "AggregationSpec",
    "CompilationResult",
    "ExecutionPlan",
    "FilterOp",
    "FilterSpec",
    "QueryCompiler",
    "QueryExecutor",
    "QuerySpec",
    "ResultSet",
    "SortDir",
    "SortSpec",
    "TimeGrain",
]