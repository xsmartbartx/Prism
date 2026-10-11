"""Shared test fixtures for Prism unit tests."""

from __future__ import annotations

from typing import Any

import pytest

from core.types import (
    IntegerType,
    FloatType,
    StringType,
    DateType,
    BooleanType,
)
from core.errors import ParseError


@pytest.fixture
def int_en() -> IntegerType:
    """Integer type with en_US locale."""
    return IntegerType(locale="en_US")


@pytest.fixture
def int_de() -> IntegerType:
    """Integer type with de_DE locale."""
    return IntegerType(locale="de_DE")


@pytest.fixture
def float_en() -> FloatType:
    """Float type with en_US locale."""
    return FloatType(locale="en_US")


@pytest.fixture
def float_de() -> FloatType:
    """Float type with de_DE locale."""
    return FloatType(locale="de_DE")


@pytest.fixture
def float_fr() -> FloatType:
    """Float type with fr_FR locale."""
    return FloatType(locale="fr_FR")


@pytest.fixture
def str_type() -> StringType:
    """Default string type."""
    return StringType()


@pytest.fixture
def date_type() -> DateType:
    """Default date type."""
    return DateType(locale="en_US")


@pytest.fixture
def date_eu() -> DateType:
    """Date type with EU locale preferences."""
    return DateType(locale="de_DE")


@pytest.fixture
def bool_type() -> BooleanType:
    """Default boolean type."""
    return BooleanType()