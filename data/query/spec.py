"""Query Spec schema — the single declarative form of every question.

Per ADR-0003 D5: Every question asked of the platform is expressed as a
Query Spec. There is no surface that accepts raw SQL.

Phase 0 v0 scope:
- Single dataset only (no joins)
- GROUP BY with scalar aggregations
- Typed filters with bound values
- Sort and limit
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AggFunction(str, Enum):
    """Supported aggregation functions."""

    SUM = "sum"
    AVG = "avg"
    COUNT = "count"
    MIN = "min"
    MAX = "max"


class FilterOp(str, Enum):
    """Supported filter operators."""

    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"


class SortDir(str, Enum):
    """Sort direction."""

    ASC = "asc"
    DESC = "desc"


class AggregationSpec(BaseModel):
    """One measure aggregation: column + function."""

    column: str = Field(min_length=1, description="The column to aggregate.")
    function: AggFunction = Field(description="The aggregation function to apply.")


class FilterSpec(BaseModel):
    """One typed filter: column + operator + bound value.

    Values are always bound parameters — never interpolated into a query string.
    """

    column: str = Field(min_length=1, description="The column to filter on.")
    operator: FilterOp = Field(description="Comparison operator.")
    value: Any = Field(description="The bound value to compare against.")


class SortSpec(BaseModel):
    """One sort directive: column + direction."""

    column: str = Field(min_length=1, description="The column to sort by.")
    direction: SortDir = Field(default=SortDir.ASC, description="Sort direction.")


class QuerySpec(BaseModel):
    """Declarative query specification.

    Every question — chart, exploration, alert, API, agent — uses this form.
    """

    dimensions: list[str] = Field(
        default_factory=list,
        description="Fields to group by (GROUP BY columns).",
    )

    measures: list[AggregationSpec] = Field(
        default_factory=list,
        description="Columns to aggregate with functions (e.g., sum(revenue)).",
    )

    filters: list[FilterSpec] = Field(
        default_factory=list,
        description="Row-level predicates. Values are bound, never interpolated.",
    )

    sort: list[SortSpec] = Field(
        default_factory=list,
        description="Sort directives (field + direction).",
    )

    limit: int | None = Field(
        default=None,
        description="Maximum rows to return. Compiler injects default when absent.",
        ge=1,
    )

    offset: int = Field(
        default=0,
        description="Rows to skip before returning results.",
        ge=0,
    )

    class Config:
        frozen = True  # Immutable — QuerySpec is always value-semantic