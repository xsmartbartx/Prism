"""String type for Prism datasets.

Strings are the universal fallback type. Every column can be parsed as
a string. The string type preserves the original text exactly.
"""

from __future__ import annotations

from typing import Any

from core.errors import ParseError
from core.types.base import DataType


class StringType(DataType):
    """A text value. The universal fallback type."""

    def __init__(self, locale: str = "en_US") -> None:
        self._locale = locale

    @property
    def name(self) -> str:
        return "string"

    @property
    def locale(self) -> str:
        return self._locale

    def parse(self, value: str) -> str:
        if not isinstance(value, str):
            raise ParseError(f"Cannot parse non-string value: {value!r}")
        return value.strip()

    def validate(self, value: Any) -> bool:
        return isinstance(value, str)

    def eq(self, a: str, b: str) -> bool:
        """Case-sensitive string comparison."""
        return a == b

    def lt(self, a: str, b: str) -> bool:
        """Lexicographic string comparison."""
        return a < b

    def gt(self, a: str, b: str) -> bool:
        """Lexicographic string comparison."""
        return a > b