"""Date type for Prism datasets.

Supports ISO 8601, US, and European date formats. The type stores
dates as Python date objects internally.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from core.errors import ParseError
from core.types.base import DataType

# Common date format patterns
DATE_FORMATS: list[str] = [
    "%Y-%m-%d",       # 2026-09-08 (ISO 8601)
    "%Y/%m/%d",       # 2026/09/08
    "%m/%d/%Y",       # 09/08/2026 (US)
    "%d/%m/%Y",       # 08/09/2026 (EU)
    "%m-%d-%Y",       # 09-08-2026
    "%d-%m-%Y",       # 08-09-2026
    "%B %d, %Y",      # September 8, 2026
    "%b %d, %Y",      # Sep 8, 2026
    "%d %B %Y",       # 8 September 2026
    "%Y%m%d",         # 20260908
]


class DateType(DataType):
    """A calendar date (year, month, day) without time component."""

    def __init__(self, locale: str = "en_US") -> None:
        self._locale = locale
        # For locale-aware format preferences
        if locale.startswith("en"):
            self._preferred_formats = DATE_FORMATS
        else:
            # EU locales prefer dd/mm/yyyy before mm/dd/yyyy
            self._preferred_formats = [
                "%d/%m/%Y",
                "%d-%m-%Y",
                "%Y-%m-%d",
                "%Y/%m/%d",
                "%m/%d/%Y",
                "%m-%d-%Y",
            ] + [f for f in DATE_FORMATS if "/" not in f and "-" not in f]

    @property
    def name(self) -> str:
        return "date"

    @property
    def locale(self) -> str:
        return self._locale

    def parse(self, value: str) -> date:
        if not isinstance(value, str):
            raise ParseError(f"Cannot parse non-string value: {value!r}")

        cleaned = value.strip()
        if not cleaned:
            raise ParseError("Cannot parse empty string as date")

        # Try Excel serial number (integer >= 60 is a date serial)
        try:
            serial = int(cleaned)
            if serial >= 60:  # Excel serial numbers start at 1 (1900-01-01)
                from datetime import timedelta

                # Excel epoch: 1899-12-30 (the -1 accounts for the leap year bug)
                excel_epoch = date(1899, 12, 30)
                return excel_epoch + timedelta(days=serial)
        except ValueError:
            pass

        # Try each format
        for fmt in self._preferred_formats:
            try:
                dt = datetime.strptime(cleaned, fmt)
                return dt.date()
            except ValueError:
                continue

        raise ParseError(
            f"Cannot parse '{value}' as date (locale={self._locale})"
        )

    def format(self, value: date) -> str:
        """Format a date as ISO 8601 by default."""
        if isinstance(value, date) and not isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, datetime):
            return value.date().isoformat()
        return str(value)

    def validate(self, value: Any) -> bool:
        return isinstance(value, date) and not isinstance(value, datetime)

    def eq(self, a: date, b: date) -> bool:
        return a == b

    def lt(self, a: date, b: date) -> bool:
        return a < b

    def gt(self, a: date, b: date) -> bool:
        return a > b