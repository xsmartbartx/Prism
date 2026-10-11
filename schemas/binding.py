"""Source Binding schema — the declarative contract for ingestion.

A Source Binding is a versioned, reviewable document that specifies:
  - the connector and source structure
  - the per-column contract (type, locale, role, drift policy)
  - refresh mode and scheduling

This is the "what" — the Binding Compiler transforms it into an
immutable Import Plan (the "how").
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from core.types import ColumnContract


class RefreshMode(str, Enum):
    """How this binding refreshes its data."""

    SNAPSHOT = "snapshot"          # Full replace on every refresh
    APPEND = "append"              # Add new rows, preserving existing
    UPSERT = "upsert"              # Add or replace rows by identity key
    PARTITION_REPLACE = "partition_replace"  # Replace one partition


class ConnectorType(str, Enum):
    """Supported connector types for Phase 0."""

    SPREADSHEET = "spreadsheet"    # Excel (.xlsx, .xls)
    CSV = "csv"                   # Delimited text files
    # More connectors added in Phase 1+


class SourceBinding(BaseModel):
    """Declarative document that defines how a source becomes a dataset.

    Immutable once published. Changes produce a new version.
    """

    name: str = Field(
        min_length=1,
        description="Human-readable binding name (e.g., 'Monthly Sales Report')."
    )

    version: str = Field(
        default="0.1.0",
        description="Semantic version of this binding document.",
    )

    connector_type: ConnectorType = Field(
        description="Which connector to use for this source.",
    )

    source: str = Field(
        description=(
            "Source specification. For files: path or URI. "
            "For databases: connection string reference."
        ),
    )

    sheet_name: str | None = Field(
        default=None,
        description="Sheet/tab name within a workbook. Required for spreadsheet connector.",
    )

    header_row_index: int = Field(
        default=0,
        description="0-based row index of the header row.",
    )

    data_start_row: int | None = Field(
        default=None,
        description=(
            "0-based row index where data begins. "
            "Defaults to header_row_index + 1 if not set."
        ),
    )

    columns: list[ColumnContract] = Field(
        min_length=1,
        description="The column contracts defining this dataset's schema.",
    )

    refresh_mode: RefreshMode = Field(
        default=RefreshMode.SNAPSHOT,
        description="How data is refreshed (snapshot, append, upsert).",
    )

    identity_columns: list[str] | None = Field(
        default=None,
        description=(
            "Column names that define a unique row for upsert mode. "
            "Required when refresh_mode is 'upsert'."
        ),
    )

    description: str | None = Field(
        default=None,
        description="Human-readable description of what this binding represents.",
    )

    tags: list[str] = Field(
        default_factory=list,
        description="Tags for categorization and discovery.",
    )

    created_at: datetime | None = Field(
        default=None,
        description="Timestamp when this binding version was created.",
    )

    def validate_binding(self) -> None:
        """Validate the binding for internal consistency.

        Raises ValidationError if the binding is invalid.
        """
        from core.validation import assert_positive_int, assert_non_empty_string

        assert_non_empty_string(self.name, name="binding.name")
        assert_non_empty_string(self.source, name="binding.source")

        if self.refresh_mode == RefreshMode.UPSERT:
            if not self.identity_columns:
                from core.errors import ValidationError
                raise ValidationError(
                    "identity_columns are required when refresh_mode is 'upsert'"
                )

        # Validate each column contract
        for col in self.columns:
            col.validate_contract()

        # Validate that identity columns exist if specified
        if self.identity_columns:
            col_names = {c.name for c in self.columns}
            for id_col in self.identity_columns:
                if id_col not in col_names:
                    from core.errors import ValidationError
                    raise ValidationError(
                        f"Identity column '{id_col}' not found in binding columns"
                    )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "name": self.name,
            "version": self.version,
            "connector_type": self.connector_type.value,
            "source": self.source,
            "sheet_name": self.sheet_name,
            "header_row_index": self.header_row_index,
            "data_start_row": self.data_start_row,
            "columns": [c.to_dict() for c in self.columns],
            "refresh_mode": self.refresh_mode.value,
            "identity_columns": self.identity_columns,
            "description": self.description,
            "tags": self.tags,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }