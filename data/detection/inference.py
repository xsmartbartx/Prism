"""Type inference engine — converts raw column data into ranked type candidates.

Strategy per ADR-0003 D1:
  1. For each column, try parsing every non-empty value against each type.
  2. Score each type by how many values successfully parse.
  3. Rank candidates by score, highest first.
  4. Flag as ambiguous if best candidate's confidence < threshold.
  5. Ambiguity blocks publication — requires human resolution.
"""

from __future__ import annotations

from core.types import (
    IntegerType,
    FloatType,
    StringType,
    DateType,
    BooleanType,
)
from data.detection.models import (
    TypeCandidate,
    ColumnInferenceResult,
    InferenceResult,
)

# Ordered list of (type_name, DataType constructor) to test
_TYPE_TESTS: list[tuple[str, str]] = [
    ("boolean", "boolean"),
    ("integer", "integer"),
    ("float", "float"),
    ("date", "date"),
    ("string", "string"),
]


def _build_type_instance(type_name: str, locale: str) -> object:
    """Create a type instance by name."""
    if type_name == "integer":
        return IntegerType(locale=locale)
    elif type_name == "float":
        return FloatType(locale=locale)
    elif type_name == "string":
        return StringType(locale=locale)
    elif type_name == "date":
        return DateType(locale=locale)
    elif type_name == "boolean":
        return BooleanType(locale=locale)
    else:
        raise ValueError(f"Unknown type: {type_name}")


class TypeInferenceEngine:
    """Engine that infers column types from sampled data."""

    def __init__(
        self,
        locale: str = "en_US",
        confidence_threshold: float = 0.8,
        max_sample: int = 1000,
    ) -> None:
        self._locale = locale
        self._confidence_threshold = confidence_threshold
        self._max_sample = max_sample

    def infer_column(
        self,
        column_name: str,
        values: list[str],
    ) -> ColumnInferenceResult:
        """Infer the best type for a single column from sampled values.

        Args:
            column_name: The name of the column.
            values: Sampled string values from the column.

        Returns:
            A ColumnInferenceResult with ranked candidates.
        """
        non_empty = [v for v in values if v and v.strip()]
        total = len(non_empty)
        if total == 0:
            return ColumnInferenceResult(
                column_name=column_name,
                candidates=[
                    TypeCandidate(
                        type_name="string",
                        confidence=1.0,
                        parsable_count=0,
                        total_count=0,
                    )
                ],
                is_ambiguous=False,
            )

        if total > self._max_sample:
            non_empty = non_empty[: self._max_sample]

        # Test each type against the values
        candidates: list[TypeCandidate] = []
        for type_name, _ in _TYPE_TESTS:
            type_instance = _build_type_instance(type_name, self._locale)
            parsable_count = 0
            samples: list[str] = []
            failures: list[str] = []

            for value in non_empty:
                try:
                    type_instance.parse(value)
                    parsable_count += 1
                    if len(samples) < 5:
                        samples.append(value)
                except Exception:
                    if len(failures) < 3:
                        failures.append(value)

            confidence = parsable_count / total
            candidates.append(
                TypeCandidate(
                    type_name=type_name,
                    confidence=round(confidence, 4),
                    parsable_count=parsable_count,
                    total_count=total,
                    sample_values=samples,
                    failure_samples=failures,
                )
            )

        candidates.sort(key=lambda c: c.confidence, reverse=True)
        best = candidates[0]
        is_ambiguous = best.confidence < self._confidence_threshold

        return ColumnInferenceResult(
            column_name=column_name,
            candidates=candidates,
            is_ambiguous=is_ambiguous,
        )

    def infer_dataset(
        self,
        column_data: dict[str, list[str]],
    ) -> InferenceResult:
        """Infer types for all columns in a dataset.

        Args:
            column_data: Dictionary mapping column names to lists of values.

        Returns:
            An InferenceResult with per-column inferences.
        """
        columns: list[ColumnInferenceResult] = []
        for col_name, values in column_data.items():
            result = self.infer_column(col_name, values)
            columns.append(result)

        overall_ambiguous = any(c.is_ambiguous for c in columns)
        return InferenceResult(
            columns=columns,
            overall_ambiguous=overall_ambiguous,
        )