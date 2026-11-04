"""API request/response models shared by services and routes."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.types.base import DataRole

PRISM_TYPES = ("integer", "float", "string", "date", "boolean")


class ColumnDecision(BaseModel):
    """A reviewer's decision for one proposed column."""

    index: int = Field(ge=0)
    source_name: str = ""
    name: str = Field(min_length=1, max_length=120)
    type: str = Field(pattern="^(integer|float|string|date|boolean)$")
    role: DataRole = DataRole.DIMENSION
    locale: str | None = None
    nullable: bool = True
    include: bool = True
    description: str | None = Field(default=None, max_length=2000)


class CommitImport(BaseModel):
    """Confirm an import proposal and publish it as a dataset version."""

    dataset_name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    sheet: str | None = None
    header_row: int = Field(ge=-1)
    data_start_row: int = Field(ge=0)
    locale: str = "en_US"
    columns: list[ColumnDecision] = Field(min_length=1)
    max_quarantine_ratio: float = Field(default=0.05, ge=0.0, le=1.0)
    target_dataset_id: str | None = None
    tags: list[str] = Field(default_factory=list)


class ReproposeImport(BaseModel):
    sheet: str | None = None
    header_row: int | None = Field(default=None, ge=-1)
    locale: str | None = None


class Page(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    items: list[Any]
    total: int
