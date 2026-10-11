"""Unit tests for StringType, DateType, and BooleanType."""
from __future__ import annotations

from datetime import date

import pytest
from core.errors import ParseError
from core.types import StringType, DateType, BooleanType


# ── StringType ───────────────────────────────────────────────────────────────────


class TestStringType:
    def test_parse(self) -> None:
        t = StringType()
        assert t.parse("hello") == "hello"
        assert t.parse("  hello  ") == "hello"
        assert t.parse("") == ""

    def test_parse_preserves_case(self) -> None:
        t = StringType()
        assert t.parse("Hello World") == "Hello World"

    def test_validate(self) -> None:
        t = StringType()
        assert t.validate("hello") is True
        assert t.validate("") is True
        assert t.validate(42) is False
        assert t.validate(None) is False  # type: ignore[arg-type]

    def test_comparison(self) -> None:
        t = StringType()
        assert t.eq("a", "a") is True
        assert t.eq("a", "b") is False
        assert t.lt("a", "b") is True
        assert t.gt("b", "a") is True

    def test_case_sensitive(self) -> None:
        t = StringType()
        assert t.eq("Hello", "hello") is False

    def test_name(self) -> None:
        assert StringType().name == "string"


# ── DateType ─────────────────────────────────────────────────────────────────────


class TestDateType:
    def test_parse_iso(self) -> None:
        t = DateType(locale="en_US")
        assert t.parse("2026-09-08") == date(2026, 9, 8)

    def test_parse_us(self) -> None:
        t = DateType(locale="en_US")
        assert t.parse("09/08/2026") == date(2026, 9, 8)

    def test_parse_eu_with_eu_locale(self) -> None:
        """de_DE: dd/mm/yyyy preferred, so 09/08/2026 → August 9"""
        t = DateType(locale="de_DE")
        assert t.parse("09/08/2026") == date(2026, 8, 9)

    def test_parse_excel_serial(self) -> None:
        """Excel serial number 44247 → 2021-02-20"""
        t = DateType(locale="en_US")
        # Excel serial 44247 computed from epoch 1899-12-30
        assert t.parse("44247") == date(2021, 2, 20)

    def test_parse_named_month(self) -> None:
        t = DateType(locale="en_US")
        assert t.parse("September 8, 2026") == date(2026, 9, 8)
        assert t.parse("Sep 8, 2026") == date(2026, 9, 8)
        assert t.parse("8 September 2026") == date(2026, 9, 8)

    def test_format(self) -> None:
        t = DateType(locale="en_US")
        assert t.format(date(2026, 9, 8)) == "2026-09-08"

    def test_validate(self) -> None:
        t = DateType(locale="en_US")
        assert t.validate(date(2026, 9, 8)) is True
        assert t.validate("2026-09-08") is False
        assert t.validate(None) is False  # type: ignore[arg-type]

    def test_comparison(self) -> None:
        t = DateType(locale="en_US")
        assert t.eq(date(2026, 1, 1), date(2026, 1, 1)) is True
        assert t.lt(date(2026, 1, 1), date(2026, 6, 1)) is True
        assert t.gt(date(2026, 6, 1), date(2026, 1, 1)) is True

    def test_name(self) -> None:
        assert DateType(locale="en_US").name == "date"


# ── BooleanType ──────────────────────────────────────────────────────────────────


class TestBooleanType:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("true", True),
            ("True", True),
            ("TRUE", True),
            ("yes", True),
            ("Yes", True),
            ("y", True),
            ("1", True),
            ("t", True),
            ("on", True),
            ("false", False),
            ("False", False),
            ("FALSE", False),
            ("no", False),
            ("No", False),
            ("n", False),
            ("0", False),
            ("f", False),
            ("off", False),
        ],
    )
    def test_parse(self, value: str, expected: bool) -> None:
        t = BooleanType()
        assert t.parse(value) is expected

    @pytest.mark.parametrize("value", ["", "maybe", "2", "oui", "nah", "   "])
    def test_parse_failure(self, value: str) -> None:
        t = BooleanType()
        with pytest.raises(ParseError):
            t.parse(value)

    def test_format(self) -> None:
        t = BooleanType()
        assert t.format(True) == "true"
        assert t.format(False) == "false"

    def test_validate(self) -> None:
        t = BooleanType()
        assert t.validate(True) is True
        assert t.validate(False) is True
        assert t.validate(1) is False
        assert t.validate(0) is False
        assert t.validate("true") is False
        assert t.validate(None) is False  # type: ignore[arg-type]

    def test_name(self) -> None:
        assert BooleanType().name == "boolean"