"""Load runner — apply a column contract to raw rows, producing typed Arrow tables.

Every row either conforms to the contract and lands in the dataset, or
it lands in the quarantine table with the reason it was rejected. No
row is silently coerced, dropped or defaulted. If the quarantine ratio
exceeds the binding's tolerance, the whole load fails — a mostly-broken
file must never become a mostly-empty dataset.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import pyarrow as pa

from core.errors import DriftDetected, ParseError, ValidationError
from core.nulls import DEFAULT_NULL_TOKENS
from core.types import BooleanType, DateType, FloatType, IntegerType, StringType
from core.types.base import DataType
from core.types.column import DriftPolicy
from data.load.store import arrow_schema


@dataclass(frozen=True)
class LoadColumn:
    """One contract column resolved against the source layout."""

    name: str
    type: str
    locale: str = "en_US"
    nullable: bool = True
    source_name: str | None = None
    source_index: int | None = None
    drift_policy: DriftPolicy = DriftPolicy.FAIL


@dataclass
class LoadResult:
    table: pa.Table
    quarantine: pa.Table | None
    row_count: int
    quarantine_count: int
    reasons: dict[str, int] = field(default_factory=dict)
    drift: list[str] = field(default_factory=list)

    @property
    def quarantine_ratio(self) -> float:
        total = self.row_count + self.quarantine_count
        return self.quarantine_count / total if total else 0.0


def _type(name: str, locale: str) -> DataType:
    types: dict[str, type[DataType]] = {
        "integer": IntegerType,
        "float": FloatType,
        "string": StringType,
        "date": DateType,
        "boolean": BooleanType,
    }
    if name not in types:
        raise ValidationError(f"Unknown column type '{name}'")
    return types[name](locale=locale)  # type: ignore[call-arg]


def resolve_columns(
    columns: list[LoadColumn], header: list[str], *, header_present: bool
) -> tuple[list[LoadColumn], list[str]]:
    """Bind contract columns to source positions by header name; report drift.

    Matching is by source header name (exact, then case/space-insensitive),
    falling back to the declared index only when the file has no header.
    """
    normalized = [" ".join(h.split()).lower() for h in header]
    resolved: list[LoadColumn] = []
    drift: list[str] = []
    for col in columns:
        idx: int | None = None
        if header_present and col.source_name:
            if col.source_name in header:
                idx = header.index(col.source_name)
            else:
                key = " ".join(col.source_name.split()).lower()
                if key in normalized:
                    idx = normalized.index(key)
        elif col.source_index is not None:
            idx = col.source_index
        if header_present and not col.source_name and col.source_index is not None:
            idx = col.source_index  # unnamed source column: positional
        if idx is None:
            msg = f"Column '{col.source_name or col.name}' is missing from the source"
            if col.drift_policy == DriftPolicy.FAIL:
                raise DriftDetected(msg)
            drift.append(msg)
        resolved.append(
            LoadColumn(
                name=col.name,
                type=col.type,
                locale=col.locale,
                nullable=col.nullable,
                source_name=col.source_name,
                source_index=idx,
                drift_policy=col.drift_policy,
            )
        )
    return resolved, drift


def load_rows(
    rows: list[list[str]],
    columns: list[LoadColumn],
    *,
    header_row: int,
    data_start_row: int,
    max_quarantine_ratio: float = 0.05,
    null_tokens: frozenset[str] = DEFAULT_NULL_TOKENS,
) -> LoadResult:
    """Type every data row against the contract.

    Raises:
        DriftDetected: a required column is missing, or the quarantine
            ratio exceeds ``max_quarantine_ratio``.
    """
    if not columns:
        raise ValidationError("A load needs at least one column")
    header = [c.strip() for c in rows[header_row]] if 0 <= header_row < len(rows) else []
    resolved, drift = resolve_columns(columns, header, header_present=header_row >= 0)
    parsers = [_type(c.type, c.locale) for c in resolved]

    good: dict[str, list[Any]] = {c.name: [] for c in resolved}
    bad_rows: list[dict[str, Any]] = []
    reasons: Counter[str] = Counter()

    for offset, row in enumerate(rows[data_start_row:]):
        if not any(cell.strip() for cell in row):
            continue
        values: list[Any] = []
        error: str | None = None
        reason_key = ""
        for col, parser in zip(resolved, parsers, strict=True):
            raw = (
                row[col.source_index]
                if col.source_index is not None and col.source_index < len(row)
                else ""
            )
            text = raw.strip()
            if col.type != "string" and text.lower() in null_tokens:
                text = ""
            if not text:
                if not col.nullable:
                    error = f"'{col.name}' is required but empty"
                    reason_key = error
                    break
                values.append(None)
                continue
            try:
                values.append(parser.parse(text))
            except ParseError:
                error = f"'{col.name}': cannot read '{text[:40]}' as {col.type}"
                reason_key = f"'{col.name}' is not a valid {col.type}"
                break
        if error is None:
            for col, v in zip(resolved, values, strict=True):
                good[col.name].append(v)
        else:
            reasons[reason_key] += 1
            bad_rows.append(
                {
                    "_source_row": data_start_row + offset + 1,  # 1-based like spreadsheets
                    "_reason": error,
                    "_raw": "␟".join(row)[:2000],
                }
            )

    schema = arrow_schema([(c.name, c.type) for c in resolved])
    table = pa.Table.from_pydict(good, schema=schema)
    quarantine = None
    if bad_rows:
        quarantine = pa.Table.from_pylist(
            bad_rows,
            schema=pa.schema(
                [("_source_row", pa.int64()), ("_reason", pa.string()), ("_raw", pa.string())]
            ),
        )
    result = LoadResult(
        table=table,
        quarantine=quarantine,
        row_count=table.num_rows,
        quarantine_count=len(bad_rows),
        reasons=dict(reasons.most_common(20)),
        drift=drift,
    )
    if result.quarantine_ratio > max_quarantine_ratio:
        top = "; ".join(f"{k} ({v})" for k, v in list(result.reasons.items())[:3])
        raise DriftDetected(
            f"{result.quarantine_count} of {result.row_count + result.quarantine_count} rows "
            f"({result.quarantine_ratio:.1%}) failed the column contract, above the "
            f"{max_quarantine_ratio:.0%} tolerance. Most common: {top}"
        )
    return result
