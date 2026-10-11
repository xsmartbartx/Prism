"""Unit tests for core validation primitives."""
from __future__ import annotations

import pytest
from core.errors import ValidationError, TypeMismatchError
from core.validation import (
    assert_not_null,
    assert_type,
    assert_in,
    assert_non_empty_string,
    assert_positive_int,
    assert_in_range,
)


class TestAssertNotNull:
    def test_not_null_passes(self) -> None:
        assert assert_not_null(42, name="value") == 42
        assert assert_not_null("hello", name="value") == "hello"
        assert assert_not_null([], name="value") == []

    def test_null_raises(self) -> None:
        with pytest.raises(ValidationError, match="must not be None"):
            assert_not_null(None, name="value")


class TestAssertType:
    def test_correct_type_passes(self) -> None:
        assert_type(42, int, name="count")
        assert_type("hello", str, name="text")
        assert_type(3.14, float, name="price")

    def test_wrong_type_raises(self) -> None:
        with pytest.raises(TypeMismatchError, match="must be int"):
            assert_type("42", int, name="count")
        with pytest.raises(TypeMismatchError, match="must be str"):
            assert_type(42, str, name="text")


class TestAssertIn:
    def test_in_set_passes(self) -> None:
        assert_in("a", {"a", "b", "c"}, name="letter")

    def test_not_in_set_raises(self) -> None:
        with pytest.raises(ValidationError):
            assert_in("z", {"a", "b", "c"}, name="letter")


class TestAssertNonEmptyString:
    def test_non_empty_passes(self) -> None:
        assert assert_non_empty_string("hello", name="text") == "hello"
        assert assert_non_empty_string("  hello  ", name="text") == "hello"

    def test_empty_raises(self) -> None:
        with pytest.raises(ValidationError, match="must not be empty"):
            assert_non_empty_string("", name="text")
        with pytest.raises(ValidationError, match="must not be empty"):
            assert_non_empty_string("   ", name="text")

    def test_non_string_raises(self) -> None:
        with pytest.raises(TypeMismatchError):
            assert_non_empty_string(42, name="text")  # type: ignore[arg-type]


class TestAssertPositiveInt:
    def test_positive_passes(self) -> None:
        assert assert_positive_int(1, name="count") == 1
        assert assert_positive_int(100, name="count") == 100

    def test_non_positive_raises(self) -> None:
        with pytest.raises(ValidationError):
            assert_positive_int(0, name="count")
        with pytest.raises(ValidationError):
            assert_positive_int(-1, name="count")

    def test_non_int_raises(self) -> None:
        with pytest.raises(TypeMismatchError):
            assert_positive_int(3.14, name="count")  # type: ignore[arg-type]


class TestAssertInRange:
    def test_in_range_passes(self) -> None:
        assert assert_in_range(5.0, 0.0, 10.0, name="value") == 5.0

    def test_below_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            assert_in_range(-1.0, 0.0, 10.0, name="value")

    def test_above_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            assert_in_range(11.0, 0.0, 10.0, name="value")

    def test_at_boundary(self) -> None:
        assert assert_in_range(0.0, 0.0, 10.0, name="value") == 0.0
        assert assert_in_range(10.0, 0.0, 10.0, name="value") == 10.0