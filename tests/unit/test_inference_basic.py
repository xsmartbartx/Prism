"""Tests for single-column type inference: basic types, evidence, edge cases."""
from __future__ import annotations

from data.detection.inference import TypeInferenceEngine


class TestInferColumn:
    """Tests for single-column type inference."""

    def setup_method(self) -> None:
        self.engine = TypeInferenceEngine(locale="en_US", confidence_threshold=0.8)

    def test_infer_integers(self) -> None:
        result = self.engine.infer_column("age", ["30", "25", "35", "42", "100"])
        best = result.best_candidate()
        assert best is not None
        assert best.type_name == "integer"
        assert best.confidence == 1.0
        assert result.is_ambiguous is False

    def test_infer_floats(self) -> None:
        values = ["3.14", "2.718", "1.618", "0.5", "100.0"]
        result = self.engine.infer_column("price", values)
        best = result.best_candidate()
        assert best is not None
        assert result.is_ambiguous is False

    def test_infer_booleans(self) -> None:
        values = ["true", "false", "true", "false", "true"]
        result = self.engine.infer_column("is_active", values)
        best = result.best_candidate()
        assert best is not None
        assert best.type_name == "boolean"
        assert best.confidence >= 0.8

    def test_infer_boolean_mixed(self) -> None:
        values = ["true", "false", "yes", "no", "Y"]
        result = self.engine.infer_column("flag", values)
        best = result.best_candidate()
        assert best is not None
        assert best.type_name == "boolean"
        assert result.is_ambiguous is False

    def test_infer_dates(self) -> None:
        values = ["2026-01-01", "2026-06-15", "2026-09-08", "2026-12-25"]
        result = self.engine.infer_column("order_date", values)
        best = result.best_candidate()
        assert best is not None
        assert best.type_name == "date"
        assert best.confidence == 1.0

    def test_infer_strings(self) -> None:
        values = ["Alice", "Bob", "Charlie", "Diana", "Eve"]
        result = self.engine.infer_column("name", values)
        best = result.best_candidate()
        assert best is not None
        assert best.type_name == "string"
        assert best.confidence == 1.0

    def test_infer_empty_column(self) -> None:
        result = self.engine.infer_column("empty", [])
        best = result.best_candidate()
        assert best is not None
        assert best.type_name == "string"
        assert result.is_ambiguous is False

    def test_infer_mostly_empty(self) -> None:
        values = ["", "", "42", "", "100"]
        result = self.engine.infer_column("sparse", values)
        best = result.best_candidate()
        assert best is not None
        assert result.is_ambiguous is False

    def test_column_with_evidence(self) -> None:
        """Candidates include sample values as evidence."""
        values = ["42", "100", "hello", "200", "300"]
        result = self.engine.infer_column("col", values)
        integer_candidate = next(c for c in result.candidates if c.type_name == "integer")
        assert len(integer_candidate.sample_values) > 0
        assert len(integer_candidate.failure_samples) > 0