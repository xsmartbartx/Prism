"""Value classification and column profiling utilities for structure detection."""

from __future__ import annotations

import re

from core.detection import ColumnProfile

_DATE_PATTERN = re.compile(
    r"^\d{1,4}[-/]\d{1,2}[-/]\d{1,4}$"
    r"|^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$"
    r"|^\d{4}\d{2}\d{2}$"          # YYYYMMDD compact
)

_NUMERIC_PATTERN = re.compile(
    r"^[-+]?\d+\.?\d*$"
    r"|^[-+]?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?$"
)

_BOOLEAN_VALUES: frozenset = frozenset({
    "true", "false", "yes", "no", "y", "n", "t", "f",
    "TRUE", "FALSE", "YES", "NO",
})


def classify_value(value: str) -> str:
    """Classify a string value as 'numeric', 'date', 'boolean', or 'string'.

    Order matters: boolean and date checks come before numeric to correctly
    classify '0', '1', and compact date strings like '20260908'.
    """
    cleaned = value.strip()
    if not cleaned:
        return "empty"
    # Boolean check first — "0" and "1" are both boolean and numeric,
    # but in data contexts they're more often boolean flags
    if cleaned in _BOOLEAN_VALUES:
        return "boolean"
    # Date check before numeric — compact dates look numeric
    if _DATE_PATTERN.match(cleaned):
        return "date"
    if _NUMERIC_PATTERN.match(cleaned):
        return "numeric"
    return "string"


def profile_rows(rows: list[list[str]]) -> dict[int, ColumnProfile]:
    """Build profiles for each column from sampled rows."""
    profiles: dict[int, ColumnProfile] = {}

    for row_idx, row in enumerate(rows):
        for col_idx, raw_value in enumerate(row):
            if col_idx not in profiles:
                profiles[col_idx] = ColumnProfile(index=col_idx)

            col = profiles[col_idx]
            col.total_count += 1

            classification = classify_value(raw_value)
            if classification == "empty":
                col.empty_count += 1
            else:
                col.non_null_count += 1
                if len(col.distinct_values) < 100:
                    col.distinct_values.add(raw_value.strip())

            if classification == "numeric":
                col.numeric_count += 1
            elif classification == "date":
                col.date_count += 1
            elif classification == "boolean":
                col.boolean_count += 1

    return profiles