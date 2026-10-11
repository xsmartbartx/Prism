"""Unit tests for IntegerType."""
from __future__ import annotations

import pytest
from core.errors import ParseError
from core.types import IntegerType


class TestIntegerType:
    def test_parse_simple(self) -> None:
        t = IntegerType(locale="en_US")
        assert t.parse("42") == 42
        assert t.parse("0") == 0
        assert t.parse("-1") == -1

    def test_parse_with_thousands_sep_en(self) -> None:
        t = IntegerType(locale="en_US")
        assert t.parse("1,234") == 1234
        assert t.parse("1,234,567") == 1_234_567

    def test_parse_with_thousands_sep_de(self) -> None:
        t = IntegerType(locale="de_DE")
        assert t.parse("1.234") == 1234
        assert t.parse("1.234.567") == 1_234_567

    def test_parse_whitespace(self) -> None:
        t = IntegerType(locale="en_US")
        assert t.parse("  42  ") == 42

    def test_parse_negative(self) -> None:
        t = IntegerType(locale="en_US")
        assert t.parse("-100") == -100

    def test_parse_failure(self) -> None:
        t = IntegerType(locale="en_US")
        with pytest.raises(ParseError):
            t.parse("not_an_integer")
        with pytest.raises(ParseError):
            t.parse("")
        with pytest.raises(ParseError):
            t.parse("12.5")

    def test_validate(self) -> None:
        t = IntegerType(locale="en_US")
        assert t.validate(42) is True
        assert t.validate(-1) is True
        assert t.validate(0) is True
        assert t.validate(3.14) is False
        assert t.validate("42") is False
        assert t.validate(True) is False
        assert t.validate(None) is False  # type: ignore[arg-type]

    def test_name(self) -> None:
        assert IntegerType(locale="en_US").name == "integer"

    def test_locale_property(self) -> None:
        assert IntegerType(locale="en_US").locale == "en_US"
        assert IntegerType(locale="de_DE").locale == "de_DE"