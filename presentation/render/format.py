"""Locale-aware value formatting for chart labels, tooltips and tables."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

from babel import Locale, UnknownLocaleError
from babel.dates import format_date
from babel.numbers import (
    format_compact_currency,
    format_compact_decimal,
    format_currency,
    format_decimal,
    format_percent,
)

from presentation.spec.view_spec import NumberFormat


def _loc(locale: str) -> str:
    try:
        Locale.parse(locale)
        return locale
    except (UnknownLocaleError, ValueError):
        return "en_US"


def format_number(
    value: Any,
    fmt: NumberFormat = NumberFormat.AUTO,
    *,
    locale: str = "en_US",
    currency: str = "USD",
    compact_axis: bool = False,
) -> str:
    """Format a numeric value; non-numbers pass through as text."""
    if value is None:
        return "–"
    if isinstance(value, bool):
        return "true" if value else "false"
    if not isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return "–"
    loc = _loc(locale)
    if fmt == NumberFormat.PERCENT:
        return str(format_percent(value, "#,##0.#%", locale=loc))
    if fmt == NumberFormat.CURRENCY:
        if compact_axis:
            if abs(value) >= 10_000:
                return str(format_compact_currency(value, currency, locale=loc, fraction_digits=1))
            return str(
                format_currency(value, currency, format="¤#,##0", locale=loc, currency_digits=False)
            )
        return str(format_currency(value, currency, locale=loc))
    if fmt == NumberFormat.COMPACT or (compact_axis and abs(value) >= 10_000):
        return str(format_compact_decimal(value, locale=loc, fraction_digits=1))
    if fmt == NumberFormat.INTEGER:
        return str(format_decimal(round(value), "#,##0", locale=loc))
    if fmt == NumberFormat.DECIMAL:
        return str(format_decimal(value, "#,##0.00", locale=loc))
    # AUTO: integers plainly, floats with up to 2 decimals (more for tiny values)
    if isinstance(value, int) or float(value).is_integer():
        return str(format_decimal(value, "#,##0", locale=loc))
    pattern = "#,##0.##" if abs(value) >= 1 else "#,##0.####"
    return str(format_decimal(value, pattern, locale=loc))


def as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and len(value) >= 10 and value[4] == "-" and value[7] == "-":
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def format_category(value: Any, *, locale: str = "en_US", time_grain: str | None = None) -> str:
    """Format an axis category (dates by grain, numbers by locale)."""
    if value is None:
        return "(blank)"
    d = as_date(value)
    loc = _loc(locale)
    if d is not None:
        if time_grain == "year":
            return str(d.year)
        if time_grain == "quarter":
            return f"Q{(d.month - 1) // 3 + 1} {d.year}"
        if time_grain == "month":
            return str(format_date(d, "MMM yyyy", locale=loc))
        return str(format_date(d, "medium", locale=loc))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return format_number(value, locale=locale)
    return str(value)
