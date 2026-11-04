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
    COUNT_DISTINCT = "count_distinct"
    MEDIAN = "median"


class FilterOp(str, Enum):
    """Supported filter operators."""

    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    NOT_IN = "not_in"
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"
    IS_NULL = "is_null"
    NOT_NULL = "not_null"
    BETWEEN = "between"


class TimeGrain(str, Enum):
    """Calendar buckets for time dimensions."""

    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


class SortDir(str, Enum):
    """Sort direction."""

    ASC = "asc"
    DESC = "desc"


class AggregationSpec(BaseModel):
    """One measure aggregation: column + function."""

    column: str = Field(
        min_length=1, description="The column to aggregate ('*' with count = row count)."
    )
    function: AggFunction = Field(description="The aggregation function to apply.")
    alias: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        description="Output column name. Defaults to the source column name.",
    )

    @property
    def output_name(self) -> str:
        if self.alias:
            return self.alias
        if self.column == "*":
            return "count"
        return self.column


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

    columns: list[str] = Field(
        default_factory=list,
        description="Raw columns to project when there are no dimensions or measures.",
    )

    time_grain: dict[str, TimeGrain] = Field(
        default_factory=dict,
        description="Bucket a date dimension by calendar grain (dimension -> grain).",
    )

    model_config = ConfigDict(frozen=True)  # Immutable — value-semantic