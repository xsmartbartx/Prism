"""Type inference data models — candidates, results, and evidence."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TypeCandidate:
    """One candidate type with confidence score and supporting evidence."""

    type_name: str
    """Name of the proposed type (e.g., 'integer', 'float')."""

    confidence: float
    """Confidence score in [0.0, 1.0]."""

    parsable_count: int = 0
    """Number of sample values that successfully parsed as this type."""

    total_count: int = 0
    """Total number of non-empty values sampled."""

    sample_values: list[str] = field(default_factory=list)
    """Up to 5 sample values that parsed as evidence."""

    failure_samples: list[str] = field(default_factory=list)
    """Up to 3 sample values that could NOT be parsed (for diagnostics)."""


@dataclass
class ColumnInferenceResult:
    """The inference result for a single column."""

    column_name: str
    """Name of the column being inferred."""

    candidates: list[TypeCandidate] = field(default_factory=list)
    """Ranked type candidates, highest confidence first."""

    is_ambiguous: bool = True
    """True if no candidate meets the required confidence threshold."""

    def best_candidate(self) -> TypeCandidate | None:
        """Return the highest-confidence candidate, or None if no candidates."""
        return self.candidates[0] if self.candidates else None


@dataclass
class InferenceResult:
    """Complete inference result for a dataset."""

    columns: list[ColumnInferenceResult] = field(default_factory=list)
    """Inference results for each column."""

    overall_ambiguous: bool = False
    """True if ANY column is ambiguous."""

    @property
    def ambiguous_columns(self) -> list[str]:
        """List of column names that are ambiguous."""
        return [c.column_name for c in self.columns if c.is_ambiguous]