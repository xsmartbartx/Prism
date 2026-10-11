"""Unit tests for SourceBinding validation, serialization, and edge cases."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.types import ColumnContract
from schemas.binding import SourceBinding, RefreshMode, ConnectorType


class TestSourceBindingValidation:
    def test_validate_binding_ok(self) -> None:
        b = SourceBinding(
            name="Test",
            connector_type=ConnectorType.CSV,
            source="/data/test.csv",
            columns=[ColumnContract(name="col", type="integer")],
        )
        b.validate_binding()

    def test_upsert_requires_identity(self) -> None:
        b = SourceBinding(
            name="Test",
            connector_type=ConnectorType.CSV,
            source="/data/test.csv",
            columns=[ColumnContract(name="id", type="integer")],
            refresh_mode=RefreshMode.UPSERT,
        )
        with pytest.raises(Exception, match="identity_columns"):
            b.validate_binding()

    def test_identity_column_must_exist(self) -> None:
        b = SourceBinding(
            name="Test",
            connector_type=ConnectorType.CSV,
            source="/data/test.csv",
            columns=[ColumnContract(name="name", type="string")],
            refresh_mode=RefreshMode.UPSERT,
            identity_columns=["id"],
        )
        with pytest.raises(Exception, match="not found"):
            b.validate_binding()

    def test_data_start_row_default(self) -> None:
        b = SourceBinding(
            name="Test",
            connector_type=ConnectorType.CSV,
            source="/data/test.csv",
            columns=[ColumnContract(name="col", type="string")],
        )
        assert b.data_start_row is None


class TestSourceBindingSerialization:
    def test_to_dict(self) -> None:
        b = SourceBinding(
            name="Test",
            connector_type=ConnectorType.SPREADSHEET,
            source="/data/test.xlsx",
            sheet_name="Data",
            columns=[
                ColumnContract(name="id", type="integer"),
                ColumnContract(name="value", type="float"),
            ],
            tags=["test"],
        )
        d = b.to_dict()
        assert d["name"] == "Test"
        assert d["connector_type"] == "spreadsheet"
        assert d["source"] == "/data/test.xlsx"
        assert d["sheet_name"] == "Data"
        assert d["refresh_mode"] == "snapshot"
        assert len(d["columns"]) == 2
        assert d["columns"][0]["name"] == "id"
        assert d["columns"][0]["type"] == "integer"

    def test_to_dict_with_timestamp(self) -> None:
        ts = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)
        b = SourceBinding(
            name="Test",
            connector_type=ConnectorType.CSV,
            source="/data/test.csv",
            columns=[ColumnContract(name="col", type="string")],
            created_at=ts,
        )
        d = b.to_dict()
        assert "2026-09-08T12:00:00" in d["created_at"]

    def test_to_dict_no_timestamp(self) -> None:
        b = SourceBinding(
            name="Test",
            connector_type=ConnectorType.CSV,
            source="/data/test.csv",
            columns=[ColumnContract(name="col", type="string")],
        )
        d = b.to_dict()
        assert d["created_at"] is None


class TestSourceBindingEdgeCases:
    def test_multiple_identity_columns(self) -> None:
        """Upsert with composite key."""
        b = SourceBinding(
            name="Orders",
            connector_type=ConnectorType.CSV,
            source="/data/orders.csv",
            columns=[
                ColumnContract(name="order_id", type="integer"),
                ColumnContract(name="line_item", type="integer"),
                ColumnContract(name="product", type="string"),
            ],
            refresh_mode=RefreshMode.UPSERT,
            identity_columns=["order_id", "line_item"],
        )
        b.validate_binding()

    def test_append_mode_no_identity(self) -> None:
        """Append mode does NOT require identity columns."""
        b = SourceBinding(
            name="Log",
            connector_type=ConnectorType.CSV,
            source="/data/log.csv",
            columns=[ColumnContract(name="event", type="string")],
            refresh_mode=RefreshMode.APPEND,
        )
        b.validate_binding()