"""Unit tests for SourceBinding creation and basic validation."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError as PydanticValidationError

from core.types import ColumnContract, DataRole
from schemas.binding import SourceBinding, RefreshMode, ConnectorType


class TestSourceBindingCreation:
    def test_minimal_binding(self) -> None:
        """A binding with just the essentials."""
        b = SourceBinding(
            name="Monthly Sales",
            connector_type=ConnectorType.SPREADSHEET,
            source="/data/sales.xlsx",
            sheet_name="Sheet1",
            columns=[
                ColumnContract(name="date", type="date"),
                ColumnContract(name="revenue", type="float"),
            ],
        )
        assert b.name == "Monthly Sales"
        assert b.connector_type == ConnectorType.SPREADSHEET
        assert b.source == "/data/sales.xlsx"
        assert b.sheet_name == "Sheet1"
        assert b.header_row_index == 0
        assert b.refresh_mode == RefreshMode.SNAPSHOT
        assert b.version == "0.1.0"
        assert len(b.columns) == 2

    def test_full_binding(self) -> None:
        """A fully specified binding."""
        b = SourceBinding(
            name="Quarterly Budget",
            version="1.2.0",
            connector_type=ConnectorType.CSV,
            source="/data/budget.csv",
            header_row_index=1,
            data_start_row=2,
            columns=[
                ColumnContract(name="department", type="string"),
                ColumnContract(name="budget", type="float", role=DataRole.MEASURE),
                ColumnContract(name="spend", type="float", role=DataRole.MEASURE),
            ],
            refresh_mode=RefreshMode.UPSERT,
            identity_columns=["department"],
            description="Departmental budget tracking",
            tags=["budget", "finance"],
        )
        assert b.name == "Quarterly Budget"
        assert b.version == "1.2.0"
        assert b.header_row_index == 1
        assert b.data_start_row == 2
        assert b.refresh_mode == RefreshMode.UPSERT
        assert b.identity_columns == ["department"]
        assert b.description == "Departmental budget tracking"
        assert len(b.tags) == 2

    def test_no_columns_raises(self) -> None:
        """A binding must have at least one column."""
        with pytest.raises(PydanticValidationError):
            SourceBinding(
                name="Empty",
                connector_type=ConnectorType.CSV,
                source="/data/empty.csv",
                columns=[],
            )

    def test_empty_name_raises(self) -> None:
        """Empty name should be rejected."""
        with pytest.raises(PydanticValidationError):
            SourceBinding(
                name="",
                connector_type=ConnectorType.CSV,
                source="/data/file.csv",
                columns=[ColumnContract(name="col", type="string")],
            )