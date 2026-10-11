"""Integer type for Prism datasets.

Locale-aware integer parsing handles thousands separators:
  - en_US: 1,234,567
  - de_DE: 1.234.567
"""

from __future__ import annotations

from typing import Any

from core.errors import ParseError
from core.types.base import DataType


class IntegerType(DataType):
    """A signed integer value."""

    def __init__(self, locale: str = "en_US") -> None:
        self._locale = locale

    @property
    def name(self) -> str:
        return "integer"

    @property
    def locale(self) -> str:
        return self._locale

    def parse(self, value: str) -> int:
        if not isinstance(value, str):
            raise ParseError(f"Cannot parse non-string value: {value!r}")

        cleaned = value.strip()
        if not cleaned:
            raise ParseError("Cannot parse empty string as integer")

        # Determine the thousands separator based on locale
        if self._locale.startswith("de") or self._locale.startswith("fr"):
            # de_DE, fr_FR: 1.234.567,89
            sep = "."
        elif self._locale.startswith("en"):
            # en_US: 1,234,567
            sep = ","
        else:
            sep = ","  # default

        # Remove thousands separators
        if sep in cleaned:
            # Remove all occurrences of the separator
            cleaned = cleaned.replace(sep, "")

        try:
            return int(cleaned)
        except ValueError:
            raise ParseError(f"Cannot parse '{value}' as integer (locale={self._locale})")

    def validate(self, value: Any) -> bool:
        return isinstance(value, int) and not isinstance(value, bool)