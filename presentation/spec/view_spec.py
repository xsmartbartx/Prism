"""View Spec schema — the declarative grammar of a visual.

Per ADR-0003 D4: Visual output is defined by a View Spec — a declarative
grammar of mark, encodings, scales, guides, and formatting metadata,
referencing a query spec rather than embedding data or SQL.

Phase 0 v0: Bar, line, table; SVG target.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MarkType(str, Enum):
    """Geometric primitives a chart draws."""

    BAR = "bar"
    LINE = "line"
    TABLE = "table"


class ScaleType(str, Enum):
    """How values are mapped to visual space."""

    LINEAR = "linear"
    ORDINAL = "ordinal"


class EncodingChannel(str, Enum):
    """Visual channels that data fields can be mapped to."""

    X = "x"
    Y = "y"
    COLOR = "color"
    SIZE = "size"


class Encoding(BaseModel):
    """One mapping from a data field to a visual channel."""

    channel: EncodingChannel = Field(
        description="The visual channel (x, y, color, size).",
    )
    field: str = Field(
        min_length=1,
        description="The data field (column name) to encode.",
    )
    scale_type: ScaleType = Field(
        default=ScaleType.LINEAR,
        description="How values in this channel are scaled.",
    )
    label: str | None = Field(
        default=None,
        description="Human-readable axis or legend label. Falls back to field name.",
    )


class ScaleConfig(BaseModel):
    """Configuration for a single scale (per channel)."""

    domain_min: float | None = Field(
        default=None,
        description="Override the scale minimum (e.g., force y-axis to start at 0).",
    )
    domain_max: float | None = Field(
        default=None,
        description="Override the scale maximum.",
    )
    nice: bool = Field(
        default=True,
        description="Round scale bounds to 'nice' values (e.g., 0, 100 rather than 0, 97).",
    )


class GuideConfig(BaseModel):
    """Configuration for axis guides."""

    title: str | None = Field(
        default=None,
        description="Axis title. Falls back to the encoding label or field name.",
    )
    show_ticks: bool = Field(default=True, description="Whether to show tick marks.")
    show_labels: bool = Field(default=True, description="Whether to show tick labels.")


class ViewSpec(BaseModel):
    """Declarative chart specification.

    A ViewSpec is a complete description of a visual: what data to show,
    how to encode it, and how to render it. It is non-Turing-complete
    and references a query spec rather than embedding data.
    """

    mark: MarkType = Field(description="The geometric primitive: bar, line, or table.")

    encodings: list[Encoding] = Field(
        min_length=1,
        description="Mappings from data fields to visual channels. "
        "At minimum, x and y are required for bar/line charts.",
    )

    scales: dict[EncodingChannel, ScaleConfig] = Field(
        default_factory=dict,
        description="Per-channel scale overrides. Missing channels get defaults.",
    )

    guides: dict[EncodingChannel, GuideConfig] = Field(
        default_factory=dict,
        description="Per-channel guide configuration (axes, legends).",
    )

    title: str | None = Field(
        default=None,
        description="Chart title. Displayed above the visualization.",
    )

    width: int = Field(
        default=800,
        description="Chart width in pixels.",
        ge=200,
        le=4000,
    )

    height: int = Field(
        default=400,
        description="Chart height in pixels.",
        ge=100,
        le=4000,
    )

    model_config = ConfigDict(frozen=True)

    def encoding_for(self, channel: EncodingChannel) -> Encoding | None:
        """Get the encoding for a given visual channel, or None."""
        for e in self.encodings:
            if e.channel == channel:
                return e
        return None