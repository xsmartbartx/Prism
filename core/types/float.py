"""Float type for Prism datasets.

Locale-aware float parsing handles decimal and thousands separators:
  - en_US: 1,234,567.89
  - de_DE: 1.234.567,89
  - fr_FR: 1 234 567,89
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from core.errors import ParseError
from core.types.base import DataType


class FloatType(DataType):
    """A double-precision floating-point value."""

    def __init__(self, locale: str = "en_US") -> None:
        self._locale = locale

    @property
    def name(self) -> str:
        return "float"

    @property
    def locale(self) -> str:
        return self._locale

    def parse(self, value: str) -> float:
        if not isinstance(value, str):
            raise ParseError(f"Cannot parse non-string value: {value!r}")

        cleaned = value.strip()
        if not cleaned:
            raise ParseError("Cannot parse empty string as float")

        # First, determine decimal and thousands separators from locale
        if self._locale.startswith("de"):
            # de_DE: 1.234.567,89 → decimal is ",", thousands is "."
            decimal_sep = ","
            thousands_sep = "."
        elif self._locale.startswith("fr"):
            # fr_FR: 1 234 567,89 → decimal is ",", thousands is " " or "."
            decimal_sep = ","
            thousands_sep = " "
        elif self._locale.startswith("en"):
            # en_US: 1,234,567.89 → decimal is ".", thousands is ","
            decimal_sep = "."
            thousands_sep = ","
        else:
            decimal_sep = "."
            thousands_sep = ","

        # Remove thousands separators
        if thousands_sep in cleaned:
            cleaned = cleaned.replace(thousands_sep, "")

        # Replace decimal separator with "."
        if decimal_sep != ".":
            cleaned = cleaned.replace(decimal_sep, ".")

        # Handle potential space as thousands separator (fr_FR)
        if " " in cleaned:
            cleaned = cleaned.replace(" ", "")

        try:
            return float(cleaned)
        except ValueError:
            raise ParseError(
                f"Cannot parse '{value}' as float (locale={self._locale})"
            )

    def validate(self, value: Any) -> bool:
        return isinstance(value, (float, int)) and not isinstance(value, bool)