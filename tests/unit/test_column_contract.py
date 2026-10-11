"""Unit tests for ColumnContract."""
from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from core.types import ColumnContract, DriftPolicy, DataRole


class TestColumnContractCreation:
    def test_minimal_contract(self) -> None:
        """A contract with just name and type should use defaults."""
        c = ColumnContract(name="sales", type="integer")
        assert c.name == "sales"
        assert c.type == "integer"
        assert c.locale == "en_US"
        assert c.role == DataRole.DIMENSION
        assert c.nullable is True
        assert c.drift_policy == DriftPolicy.FAIL
        assert c.description is None

    def test_full_contract(self) -> None:
        """A contract with all fields specified."""
        c = ColumnContract(
            name="revenue",
            type="float",
            locale="de_DE",
            role=DataRole.MEASURE,
            nullable=False,
            drift_policy=DriftPolicy.WARN,
            description="Monthly revenue in EUR",
        )
        assert c.name == "revenue"
        assert c.type == "float"
        assert c.locale == "de_DE"
        assert c.role == DataRole.MEASURE
        assert c.nullable is False
        assert c.drift_policy == DriftPolicy.WARN
        assert c.description == "Monthly revenue in EUR"

    def test_empty_name_raises(self) -> None:
        """Empty name should be rejected by Pydantic."""
        with pytest.raises(PydanticValidationError):
            ColumnContract(name="", type="string")

    def test_invalid_type_raises_pydantic(self) -> None:
        """Pydantic won't restrict type to valid set, but our validate will."""
        c = ColumnContract(name="test", type="unknown_type")
        with pytest.raises(Exception):
            c.validate_contract()

    def test_boolean_type(self) -> None:
        c = ColumnContract(name="is_active", type="boolean")
        assert c.type == "boolean"
        c.validate_contract()  # should not raise

    def test_date_type(self) -> None:
        c = ColumnContract(name="order_date", type="date", role=DataRole.TIME)
        assert c.type == "date"
        c.validate_contract()


class TestColumnContractValidation:
    def test_validate_contract_ok(self) -> None:
        c = ColumnContract(name="valid", type="integer")
        c.validate_contract()  # should not raise

    def test_validate_contract_invalid_type(self) -> None:
        c = ColumnContract(name="bad", type="not_a_real_type")
        with pytest.raises(Exception, match="must be one of"):
            c.validate_contract()

    def test_validate_all_valid_types(self) -> None:
        for type_name in ("integer", "float", "string", "date", "boolean"):
            c = ColumnContract(name="col", type=type_name)
            c.validate_contract()  # should not raise


class TestColumnContractSerialization:
    def test_to_dict(self) -> None:
        c = ColumnContract(
            name="revenue",
            type="float",
            locale="de_DE",
            role=DataRole.MEASURE,
            nullable=False,
            drift_policy=DriftPolicy.WARN,
            description="Monthly revenue",
        )
        d = c.to_dict()
        assert d["name"] == "revenue"
        assert d["type"] == "float"
        assert d["locale"] == "de_DE"
        assert d["role"] == "measure"
        assert d["nullable"] is False
        assert d["drift_policy"] == "warn"
        assert d["description"] == "Monthly revenue"

    def test_from_dict(self) -> None:
        data = {
            "name": "sales",
            "type": "integer",
            "locale": "en_US",
            "role": "measure",
            "nullable": True,
            "drift_policy": "fail",
            "description": None,
        }
        c = ColumnContract.from_dict(data)
        assert c.name == "sales"
        assert c.type == "integer"
        assert c.role == DataRole.MEASURE

    def test_roundtrip(self) -> None:
        original = ColumnContract(
            name="price", type="float", role=DataRole.MEASURE, nullable=False
        )
        restored = ColumnContract.from_dict(original.to_dict())
        assert restored.name == original.name
        assert restored.type == original.type
        assert restored.role == original.role
        assert restored.nullable == original.nullable