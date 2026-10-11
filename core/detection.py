"""Structure detection — finding tables inside sources.

The Structure Detector analyses a source to locate:
  - Header rows (column names)
  - Data regions (where the actual records start)
  - Table boundaries (end of data, footer notes, etc.)

Each detection produces a confidence score in [0.0, 1.0]. Low-confidence
results require human confirmation — no silent guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DetectionConfidence(str, Enum):
    """Confidence level of a structural detection."""

    HIGH = "high"           # >= 0.9 — can auto-confirm
    MEDIUM = "medium"       # >= 0.7 — suggest but allow override
    LOW = "low"             # >= 0.4 — require confirmation
    NONE = "none"           # < 0.4 — require human input


@dataclass
class ColumnProfile:
    """Profile of a single column from scanning the raw data."""

    index: int
    name: str | None = None
    non_null_count: int = 0
    total_count: int = 0
    distinct_values: set[str] = field(default_factory=set)
    numeric_count: int = 0
    date_count: int = 0
    boolean_count: int = 0
    empty_count: int = 0

    @property
    def null_ratio(self) -> float:
        """Ratio of null/empty values in this column."""
        if self.total_count == 0:
            return 1.0
        return self.empty_count / self.total_count

    @property
    def numeric_ratio(self) -> float:
        """Ratio of values that look numeric."""
        if self.non_null_count == 0:
            return 0.0
        return self.numeric_count / self.non_null_count

    @property
    def cardinality(self) -> int:
        """Number of distinct non-null values."""
        return len(self.distinct_values)


@dataclass
class DetectedStructure:
    """The detected structure of a source.

    This is a proposal — the user or binding compiler may override it.
    """

    header_row_index: int
    """0-based index of the header row. -1 if no header detected."""

    data_start_row: int
    """0-based index of the first data row."""

    data_end_row: int | None = None
    """0-based index of the last data row, or None if unknown."""

    column_count: int = 0
    """Number of columns detected."""

    column_names: list[str] = field(default_factory=list)
    """Detected column names (from header row)."""

    confidence: DetectionConfidence = DetectionConfidence.NONE
    """Overall confidence in this structure detection."""

    confidence_score: float = 0.0
    """Numeric confidence score [0.0, 1.0]."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary for inspection/logging."""
        return {
            "header_row_index": self.header_row_index,
            "data_start_row": self.data_start_row,
            "data_end_row": self.data_end_row,
            "column_count": self.column_count,
            "column_names": self.column_names,
            "confidence": self.confidence.value,
            "confidence_score": self.confidence_score,
        }


def _score_to_enum(score: float) -> DetectionConfidence:
    """Convert a numeric score to a confidence enum."""
    if score >= 0.9:
        return DetectionConfidence.HIGH
    elif score >= 0.7:
        return DetectionConfidence.MEDIUM
    elif score >= 0.4:
        return DetectionConfidence.LOW
    else:
        return DetectionConfidence.NONE