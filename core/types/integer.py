"""Integer type for Prism datasets.

Locale-aware integer parsing handles thousands separators:
  - en_US: 1,234,567
  - de_DE: 1.234.567
"""

from __future__ import annotations

from typing import Any

from core.errors import ParseError
from core.types.base import DataType
from core.types.numeric import normalize_number


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
        normalized = normalize_number(cleaned, self._locale, allow_fraction=False)
        if normalized is None:
            raise ParseError(f"Cannot parse '{value}' as integer (locale={self._locale})")
        return int(normalized)

    def validate(self, value: Any) -> bool:
        return isinstance(value, int) and not isinstance(value, bool)