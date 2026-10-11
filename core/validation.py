"""Validation primitives for the Prism platform.

These are the base building blocks that all layer-specific validators
extend. The Validator at the trust boundary uses these plus schema-aware
rules to validate every inbound artifact.
"""

from __future__ import annotations

from typing import Any, TypeVar

from core.errors import ValidationError, TypeMismatchError

T = TypeVar("T")


def assert_not_null(value: T | None, *, name: str = "value") -> T:
    """Assert that a value is not None."""
    if value is None:
        raise ValidationError(f"{name} must not be None")
    return value


def assert_type(value: Any, expected: type, *, name: str = "value") -> None:
    """Assert that a value is of the expected type."""
    if not isinstance(value, expected):
        raise TypeMismatchError(
            f"{name} must be {expected.__name__}, got {type(value).__name__}"
        )


def assert_in(value: str, options: set[str], *, name: str = "value") -> None:
    """Assert that a string value is in a set of valid options."""
    if value not in options:
        valid = ", ".join(sorted(options))
        raise ValidationError(f"{name} must be one of: {valid}")


def assert_non_empty_string(value: str, *, name: str = "value") -> str:
    """Assert that a string is non-empty."""
    assert_type(value, str, name=name)
    if not value.strip():
        raise ValidationError(f"{name} must not be empty")
    return value.strip()


def assert_positive_int(value: int, *, name: str = "value") -> int:
    """Assert that an integer is positive."""
    assert_type(value, int, name=name)
    if value <= 0:
        raise ValidationError(f"{name} must be a positive integer")
    return value


def assert_in_range(
    value: float, low: float, high: float, *, name: str = "value"
) -> float:
    """Assert that a numeric value falls within [low, high]."""
    if value < low or value > high:
        raise ValidationError(f"{name} must be between {low} and {high}")
    return value