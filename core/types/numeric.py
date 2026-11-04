"""Strict, locale-aware numeric parsing shared by IntegerType and FloatType.

Lenient parsing is how a spreadsheet import silently produces a wrong
number ("1.5" read as 15 under a German locale). These rules accept a
thousands separator only in well-formed groups of three, so ambiguous
input fails to parse and surfaces as an inference decision instead.
"""

from __future__ import annotations

import re

_SPACES = " \u00a0\u202f"


def separators(locale: str) -> tuple[str, str]:
    """Return ``(thousands_chars, decimal_char)`` for a locale."""
    lang = locale.split("_")[0].lower()
    if lang in {"de", "nl", "it", "es", "pt", "id", "tr", "da"}:
        return ".", ","
    if lang in {"fr", "pl", "cs", "sk", "ru", "uk", "sv", "fi", "nb", "hu"}:
        return _SPACES + ".", ","
    return ",", "."


_CURRENCY_SYMBOLS = ("zł", "$", "€", "£", "¥", "₹", "₽")


def _strip_currency(text: str) -> str:
    t = text.strip()
    for sym in _CURRENCY_SYMBOLS:
        if t.startswith(sym):
            t = t[len(sym) :]
        if t.endswith(sym):
            t = t[: -len(sym)]
    return t.strip()


def _pattern(locale: str, *, allow_fraction: bool) -> re.Pattern[str]:
    thousands, decimal = separators(locale)
    tsep = "[" + re.escape(thousands) + "]"
    int_part = rf"(?:\d{{1,3}}(?:{tsep}\d{{3}})+|\d+)"
    if not allow_fraction:
        return re.compile(rf"^[+-]?{int_part}$")
    frac = rf"(?:{re.escape(decimal)}\d+)"
    exp = r"(?:[eE][+-]?\d+)"
    return re.compile(rf"^[+-]?(?:{int_part}{frac}?|{frac}){exp}?$")


_CACHE: dict[tuple[str, bool], re.Pattern[str]] = {}


def normalize_number(text: str, locale: str, *, allow_fraction: bool) -> str | None:
    """Return a Python-parsable numeric string, or None if ``text`` is not well-formed."""
    key = (locale, allow_fraction)
    pat = _CACHE.get(key)
    if pat is None:
        pat = _CACHE[key] = _pattern(locale, allow_fraction=allow_fraction)
    cleaned = _strip_currency(text)
    if not cleaned or not pat.match(cleaned):
        return None
    thousands, decimal = separators(locale)
    for ch in thousands:
        cleaned = cleaned.replace(ch, "")
    if decimal != ".":
        cleaned = cleaned.replace(decimal, ".")
    return cleaned
