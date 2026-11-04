"""Float type for Prism datasets.

Locale-aware float parsing handles decimal and thousands separators:
  - en_US: 1,234,567.89
  - de_DE: 1.234.567,89
  - fr_FR: 1 234 567,89
"""

from __future__ import annotations

import math
from typing import Any

from core.errors import ParseError
from core.types.base import DataType
from core.types.numeric import normalize_number


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
        normalized = normalize_number(cleaned, self._locale, allow_fraction=True)
        if normalized is None:
            raise ParseError(f"Cannot parse '{value}' as float (locale={self._locale})")
        result = float(normalized)
        if not math.isfinite(result):
            raise ParseError(f"Non-finite float '{value}' is not allowed")
        return result

    def validate(self, value: Any) -> bool:
        return isinstance(value, (float, int)) and not isinstance(value, bool)