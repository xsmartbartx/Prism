"""Query layer — Query Spec, Compiler, Executor, and Result Cache.

Phase 0 v0:
- Single-dataset queries only (no joins)
- GROUP BY with aggregations (sum, avg, count, min, max)
- Filters (eq, ne, gt, gte, lt, lte)
- Sort (asc, desc)
- Limit / offset
"""

from data.query.spec import (
    AggFunction,
    FilterOp,
    SortDir,
    AggregationSpec,
    FilterSpec,
    SortSpec,
    QuerySpec,
)
from data.query.plan import ExecutionPlan, ResultSet
from data.query.compiler import QueryCompiler, CompilationResult
from data.query.executor import QueryExecutor

__all__ = [
    "AggFunction",
    "FilterOp",
    "SortDir",
    "AggregationSpec",
    "FilterSpec",
    "SortSpec",
    "QuerySpec",
    "ExecutionPlan",
    "ResultSet",
    "QueryCompiler",
    "CompilationResult",
    "QueryExecutor",
]