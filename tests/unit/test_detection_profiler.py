"""Tests for value classification and column profiling."""
from __future__ import annotations

from data.detection.profiler import classify_value, profile_rows


class TestValueClassification:
    def test_classify_numeric(self) -> None:
        assert classify_value("42") == "numeric"
        assert classify_value("3.14") == "numeric"
        assert classify_value("-1") == "numeric"
        assert classify_value("1,234") == "numeric"

    def test_classify_date(self) -> None:
        assert classify_value("2026-09-08") == "date"
        assert classify_value("09/08/2026") == "date"
        assert classify_value("20260908") == "date"

    def test_classify_boolean(self) -> None:
        assert classify_value("true") == "boolean"
        assert classify_value("FALSE") == "boolean"
        assert classify_value("yes") == "boolean"
        assert classify_value("0") == "boolean"
        assert classify_value("1") == "boolean"

    def test_classify_string(self) -> None:
        assert classify_value("hello") == "string"
        assert classify_value("Product Name") == "string"
        assert classify_value("") == "empty"
        assert classify_value("  ") == "empty"


class TestProfileRows:
    def test_profile_simple(self) -> None:
        rows = [
            ["name", "age", "score"],
            ["Alice", "30", "95.5"],
            ["Bob", "25", "88.0"],
        ]
        profiles = profile_rows(rows)
        assert 0 in profiles
        assert 1 in profiles
        assert 2 in profiles
        assert profiles[0].numeric_ratio <= 0.5

    def test_profile_all_numeric(self) -> None:
        rows = [["100", "200", "300"], ["101", "201", "301"]]
        profiles = profile_rows(rows)
        for col_idx in range(3):
            assert profiles[col_idx].numeric_count >= 1