"""Tests for type inference: ambiguity, multi-column datasets, edge cases."""
from __future__ import annotations

from data.detection.inference import TypeInferenceEngine


class TestInferAmbiguity:
    def test_mixed_types_low_confidence(self) -> None:
        engine = TypeInferenceEngine(locale="en_US", confidence_threshold=0.9)
        values = ["42", "100", "N/A", "200", "300", "TBD", "50"]
        result = engine.infer_column("mixed", values)
        assert result.is_ambiguous is True

    def test_high_threshold_blocks(self) -> None:
        engine_strict = TypeInferenceEngine(locale="en_US", confidence_threshold=0.95)
        engine_lenient = TypeInferenceEngine(locale="en_US", confidence_threshold=0.7)
        values = ["1", "2", "3", "4", "5", "6", "7", "8", "nine", "ten"]
        assert engine_strict.infer_column("nums", values).is_ambiguous is True
        assert engine_lenient.infer_column("nums", values).is_ambiguous is False


class TestInferDataset:
    def setup_method(self) -> None:
        self.engine = TypeInferenceEngine(locale="en_US")

    def test_typical_dataset(self) -> None:
        data = {
            "name": ["Alice", "Bob", "Charlie", "Diana"],
            "age": ["30", "25", "35", "28"],
            "salary": ["75000.50", "82000.00", "95000.00", "68000.00"],
            "is_manager": ["false", "true", "true", "false"],
            "start_date": ["2024-01-15", "2023-06-01", "2025-03-20", "2024-11-01"],
        }
        result = self.engine.infer_dataset(data)
        assert result.overall_ambiguous is False
        assert len(result.columns) == 5

        type_by_name = {c.column_name: c.best_candidate().type_name for c in result.columns}
        assert type_by_name["name"] == "string"
        assert type_by_name["age"] == "integer"
        assert type_by_name["is_manager"] == "boolean"
        assert type_by_name["start_date"] == "date"

    def test_ambiguous_dataset(self) -> None:
        data = {
            "clean": ["10", "20", "30", "40"],
            "messy": ["10", "N/A", "20", "unknown", "30"],
        }
        result = self.engine.infer_dataset(data)
        assert result.overall_ambiguous is True
        assert "messy" in result.ambiguous_columns

    def test_empty_dataset(self) -> None:
        result = self.engine.infer_dataset({})
        assert result.overall_ambiguous is False
        assert len(result.columns) == 0


class TestInferEdgeCases:
    def test_all_none(self) -> None:
        engine = TypeInferenceEngine()
        result = engine.infer_column("all_empty", ["", "", "", ""])
        assert result.is_ambiguous is False
        assert result.best_candidate().type_name == "string"

    def test_boolean_and_integer(self) -> None:
        engine = TypeInferenceEngine()
        values = ["0", "1", "0", "1"]
        result = engine.infer_column("flag", values)
        best = result.best_candidate()
        assert best is not None
        assert best.type_name == "boolean"

    def test_large_sample(self) -> None:
        engine = TypeInferenceEngine(max_sample=50)
        values = [str(i) for i in range(200)]
        result = engine.infer_column("nums", values)
        assert result.best_candidate().type_name == "integer"
        assert result.is_ambiguous is False

    def test_multiple_candidates(self) -> None:
        engine = TypeInferenceEngine()
        values = ["42", "hello", "3.14", "true"]
        result = engine.infer_column("mixed", values)
        assert len(result.candidates) == 5
        assert result.candidates[0].confidence >= result.candidates[1].confidence

    def test_integer_vs_float(self) -> None:
        engine = TypeInferenceEngine()
        values = ["1", "2", "3", "4", "5"]
        result = engine.infer_column("ints", values)
        integer_candidate = next(c for c in result.candidates if c.type_name == "integer")
        assert integer_candidate.confidence >= 0.8