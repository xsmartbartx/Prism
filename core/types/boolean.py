"""Boolean type for Prism datasets.

Supports common boolean string representations:
  - true/false, yes/no, 1/0, y/n, t/f
"""

from __future__ import annotations

from typing import Any

from core.errors import ParseError
from core.types.base import DataType

_TRUE_VALUES: set[str] = {"true", "yes", "y", "1", "t", "on"}
_FALSE_VALUES: set[str] = {"false", "no", "n", "0", "f", "off"}


class BooleanType(DataType):
    """A boolean (true/false) value."""

    def __init__(self, locale: str = "en_US") -> None:
        self._locale = locale

    @property
    def name(self) -> str:
        return "boolean"

    @property
    def locale(self) -> str:
        return self._locale

    def parse(self, value: str) -> bool:
        if not isinstance(value, str):
            raise ParseError(f"Cannot parse non-string value: {value!r}")

        cleaned = value.strip().lower()
        if cleaned in _TRUE_VALUES:
            return True
        if cleaned in _FALSE_VALUES:
            return False
        raise ParseError(
            f"Cannot parse '{value}' as boolean. "
            f"Expected one of: {', '.join(sorted(_TRUE_VALUES | _FALSE_VALUES))}"
        )

    def format(self, value: bool) -> str:
        return "true" if value else "false"

    def validate(self, value: Any) -> bool:
        return isinstance(value, bool)