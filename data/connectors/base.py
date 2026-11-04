"""Connector contract types."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ConnectorLimits:
    """Resource ceilings enforced while parsing untrusted files."""

    max_rows: int = 2_000_000
    max_columns: int = 500
    max_cell_chars: int = 32_767  # Excel's own cell limit
    max_uncompressed_bytes: int = 1024 * 1024 * 1024  # zip-bomb guard for xlsx
    max_compression_ratio: float = 200.0


@dataclass
class SourceTable:
    """Raw rows read from one table-like region of a source."""

    rows: list[list[str]]
    truncated: bool = False
    encoding: str | None = None
    delimiter: str | None = None
    sheet: str | None = None
    warnings: list[str] = field(default_factory=list)
