"""Column contract — the per-column specification in a source binding.

A column contract declares everything the system needs to know about a
column: its identity, type, locale, semantic role, nullability, and
how to react if the source column drifts.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from core.types.base import DataRole
from core.validation import assert_in, assert_non_empty_string


class DriftPolicy(str, Enum):
    """How to react when a source column changes shape."""

    FAIL = "fail"        # Block the import — the default
    WARN = "warn"        # Allow import but raise a finding
    IGNORE = "ignore"    # Silently adapt (use with caution)


class ColumnContract(BaseModel):
    """Declared specification for one column in a source.

    This is the fundamental unit of the ingestion contract. A column
    contract is established at bind time and never re-inferred.
    """

    name: str = Field(
        min_length=1,
        description="Canonical column name. Must be non-empty."
    )

    type: str = Field(
        description="Prism data type name: integer, float, string, date, boolean."
    )

    locale: str = Field(
        default="en_US",
        description="Locale for parsing and formatting (e.g., 'en_US', 'de_DE').",
    )

    role: DataRole = Field(
        default=DataRole.DIMENSION,
        description="Semantic role: dimension, measure, identifier, time, etc.",
    )

    nullable: bool = Field(
        default=True,
        description="Whether null/empty values are allowed in this column.",
    )

    drift_policy: DriftPolicy = Field(
        default=DriftPolicy.FAIL,
        description="Action when the source column changes type or disappears.",
    )

    description: str | None = Field(
        default=None,
        description="Optional human-readable description of what this column represents.",
    )

    def validate_contract(self) -> None:
        """Validate that the contract is internally consistent.

        Raises ValidationError if the contract is invalid.
        """
        assert_non_empty_string(self.name, name="column.name")
        valid_types = {"integer", "float", "string", "date", "boolean"}
        assert_in(self.type, valid_types, name="column.type")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "name": self.name,
            "type": self.type,
            "locale": self.locale,
            "role": self.role.value,
            "nullable": self.nullable,
            "drift_policy": self.drift_policy.value,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ColumnContract":
        """Create a contract from a dictionary (e.g., parsed from YAML/JSON)."""
        return cls(**data)