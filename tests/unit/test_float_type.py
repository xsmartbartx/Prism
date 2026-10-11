"""Unit tests for FloatType."""
from __future__ import annotations

import pytest
from core.errors import ParseError
from core.types import FloatType


class TestFloatType:
    def test_parse_simple(self) -> None:
        t = FloatType(locale="en_US")
        assert t.parse("3.14") == 3.14
        assert t.parse("0.0") == 0.0
        assert t.parse("-2.5") == -2.5

    def test_parse_en_us(self) -> None:
        """en_US: 1,234,567.89"""
        t = FloatType(locale="en_US")
        assert t.parse("1,234.56") == 1234.56
        assert t.parse("1,234,567.89") == 1_234_567.89

    def test_parse_de_de(self) -> None:
        """de_DE: 1.234.567,89"""
        t = FloatType(locale="de_DE")
        assert t.parse("1.234,56") == 1234.56
        assert t.parse("1.234.567,89") == 1_234_567.89

    def test_parse_fr_fr(self) -> None:
        """fr_FR: 1 234 567,89"""
        t = FloatType(locale="fr_FR")
        assert t.parse("1 234,56") == 1234.56
        assert t.parse("1 234 567,89") == 1_234_567.89

    def test_parse_whitespace(self) -> None:
        t = FloatType(locale="en_US")
        assert t.parse("  3.14  ") == 3.14

    def test_parse_negative(self) -> None:
        t = FloatType(locale="en_US")
        assert t.parse("-0.001") == -0.001

    def test_parse_integer_string(self) -> None:
        t = FloatType(locale="en_US")
        assert t.parse("42") == 42.0

    def test_parse_failure(self) -> None:
        t = FloatType(locale="en_US")
        with pytest.raises(ParseError):
            t.parse("not_a_float")
        with pytest.raises(ParseError):
            t.parse("")

    def test_validate(self) -> None:
        t = FloatType(locale="en_US")
        assert t.validate(3.14) is True
        assert t.validate(42) is True
        assert t.validate("3.14") is False
        assert t.validate(True) is False

    def test_name(self) -> None:
        assert FloatType(locale="en_US").name == "float"