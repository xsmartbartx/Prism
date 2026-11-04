"""Import proposal — everything a human must confirm before a binding is published.

Given raw rows from any connector, the proposal combines structure
detection, header normalisation, locale detection, ranked type
inference and semantic-role suggestions into one reviewable document.
It is a *proposal*: nothing here is applied until a person (or an
agent under the same validation path) confirms it.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from core.nulls import is_null
from core.types.base import DataRole
from core.types.numeric import normalize_number
from data.detection.inference import TypeInferenceEngine
from data.detection.profiler import classify_value

HEADER_SCAN_ROWS = 20
INFERENCE_SAMPLE = 5000
PREVIEW_ROWS = 15
MAX_NAME_LEN = 120


@dataclass
class ColumnProposal:
    index: int
    source_name: str
    name: str
    type: str
    locale: str
    role: str
    nullable: bool
    ambiguous: bool
    null_ratio: float
    distinct_ratio: float
    candidates: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class ImportProposal:
    header_row: int
    data_start_row: int
    locale: str
    confidence: float
    columns: list[ColumnProposal]
    preview: list[list[str]]
    row_estimate: int
    warnings: list[str] = field(default_factory=list)
    sheet: str | None = None
    delimiter: str | None = None
    encoding: str | None = None

    @property
    def needs_review(self) -> bool:
        return any(c.ambiguous for c in self.columns) or self.confidence < 0.7

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["needs_review"] = self.needs_review
        return d


# ----------------------------------------------------------------------
# Header detection
# ----------------------------------------------------------------------


def _trimmed(row: list[str]) -> list[str]:
    r = list(row)
    while r and not r[-1].strip():
        r.pop()
    return r


def _row_width_mode(rows: list[list[str]]) -> int:
    widths = [len(_trimmed(r)) for r in rows if any(c.strip() for c in r)]
    if not widths:
        return 0
    return Counter(widths).most_common(1)[0][0]


def find_header_row(rows: list[list[str]]) -> tuple[int, float]:
    """Return ``(header_row_index, confidence)``; ``-1`` means no header row.

    Scans the first rows for the line that looks most like column names:
    nearly full, mostly text, unique values, and followed by rows of a
    different type mix. Title and notes rows above the table lose
    because they fill only one or two cells.
    """
    best_idx, best_score = -1, 0.0
    limit = min(len(rows), HEADER_SCAN_ROWS)
    total_nonblank = max(sum(1 for r in rows if any(c.strip() for c in r)), 1)
    nonblank_above = 0
    for i in range(limit):
        if i > 0 and any(c.strip() for c in rows[i - 1]):
            nonblank_above += 1
        cells = [c.strip() for c in _trimmed(rows[i])]
        non_empty = [c for c in cells if c]
        if not non_empty:
            continue
        below = [r for r in rows[i + 1 : i + 51] if any(c.strip() for c in r)]
        if not below:
            continue
        width = max(_row_width_mode(below), 1)
        fill = min(len(non_empty) / width, 1.0)
        if len(non_empty) == 1 and width > 1:
            fill *= 0.3  # a lone title cell
        kinds = [classify_value(c) for c in non_empty]
        text_ratio = kinds.count("string") / len(kinds)
        unique = 1.0 if len(set(non_empty)) == len(non_empty) else 0.4
        below_cells = [c.strip() for r in below[:20] for c in r if c.strip()]
        below_text = (
            sum(1 for c in below_cells if classify_value(c) == "string") / len(below_cells)
            if below_cells
            else 0.0
        )
        contrast = max(0.0, text_ratio - below_text)
        score = fill * 0.4 + text_ratio * 0.25 + unique * 0.15 + contrast * 0.2
        score -= 0.3 * nonblank_above / total_nonblank  # rows above a header are lost
        if score > best_score + 1e-9:
            best_idx, best_score = i, score
    if best_score < 0.55:
        return -1, round(1.0 - best_score, 4)
    return best_idx, round(min(best_score + 0.1, 1.0), 4)


def normalize_names(raw: list[str], width: int) -> list[str]:
    """Clean header cells into unique, non-empty column names."""
    names: list[str] = []
    seen: dict[str, int] = {}
    for i in range(width):
        base = raw[i] if i < len(raw) else ""
        base = re.sub(r"[\x00-\x1f\x7f]", " ", base)
        base = re.sub(r"\s+", " ", base).strip()[:MAX_NAME_LEN] or f"column_{i + 1}"
        key = base.lower()
        if key in seen:
            seen[key] += 1
            base = f"{base}_{seen[key]}"
            key = base.lower()
        seen.setdefault(key, 1)
        names.append(base)
    return names


# ----------------------------------------------------------------------
# Locale and role heuristics
# ----------------------------------------------------------------------


def detect_locale(column_values: list[list[str]], default: str = "en_US") -> str:
    """Pick the number locale whose separators explain the data unambiguously."""
    en_only = de_only = 0
    for values in column_values:
        for v in values[:500]:
            v = v.strip()
            if not v or not any(ch.isdigit() for ch in v):
                continue
            en = normalize_number(v, "en_US", allow_fraction=True) is not None
            de = normalize_number(v, "de_DE", allow_fraction=True) is not None
            if en and de:
                # "1.234" / "1,234": readable either way unless separators disambiguate
                continue
            if en:
                en_only += 1
            elif de:
                de_only += 1
    if de_only > en_only * 2 and de_only >= 3:
        return "de_DE"
    return default


_SLASH_DATE = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})")


def date_order(values: list[str]) -> str | None:
    """Return ``'dmy'`` / ``'mdy'`` when the data proves an order, else None."""
    day_first = month_first = 0
    for v in values[:1000]:
        m = _SLASH_DATE.match(v.strip())
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        if a > 12 >= b:
            day_first += 1
        elif b > 12 >= a:
            month_first += 1
    if day_first and not month_first:
        return "dmy"
    if month_first and not day_first:
        return "mdy"
    return None


_ID_NAME = re.compile(r"(^id$|_id$|^id_|\bid\b|uuid|guid|code$|number$|^no\.?$|sku)", re.I)
_GEO_NAME = re.compile(r"(country|city|region|state|province|zip|postal|county|lat|lon)", re.I)
_TIME_NAME = re.compile(r"(year|month|quarter|week|date|day|period)", re.I)


def suggest_role(name: str, type_name: str, distinct_ratio: float) -> DataRole:
    if type_name == "date":
        return DataRole.TIME
    if _ID_NAME.search(name) and distinct_ratio > 0.9:
        return DataRole.IDENTIFIER
    if type_name in ("integer", "float"):
        if _TIME_NAME.search(name) and type_name == "integer":
            return DataRole.TIME
        return DataRole.MEASURE
    if _GEO_NAME.search(name):
        return DataRole.GEOGRAPHY
    return DataRole.DIMENSION


# ----------------------------------------------------------------------
# Proposal builder
# ----------------------------------------------------------------------


def build_proposal(
    rows: list[list[str]],
    *,
    header_row: int | None = None,
    locale: str | None = None,
    sheet: str | None = None,
    delimiter: str | None = None,
    encoding: str | None = None,
    warnings: list[str] | None = None,
) -> ImportProposal:
    """Build a reviewable proposal from raw rows.

    ``header_row`` and ``locale`` override detection (used when the
    reviewer corrects the proposal and asks for a re-run).
    """
    warns = list(warnings or [])
    if header_row is None:
        header_idx, confidence = find_header_row(rows)
    else:
        header_idx, confidence = header_row, 1.0

    start = header_idx + 1 if header_idx >= 0 else 0
    while start < len(rows) and not any(c.strip() for c in rows[start]):
        start += 1
    data_rows = [r for r in rows[start:] if any(c.strip() for c in r)]
    width = max([_row_width_mode(data_rows)] + [len(_trimmed(r)) for r in data_rows[:200]] + [0])
    header_cells = rows[header_idx] if header_idx >= 0 else []
    width = max(width, len(_trimmed(header_cells)))
    if width == 0:
        return ImportProposal(
            header_row=header_idx,
            data_start_row=start,
            locale=locale or "en_US",
            confidence=0.0,
            columns=[],
            preview=[],
            row_estimate=0,
            warnings=[*warns, "No tabular data found"],
            sheet=sheet,
            delimiter=delimiter,
            encoding=encoding,
        )

    names = normalize_names(header_cells, width)
    sample = data_rows[:INFERENCE_SAMPLE]
    col_values = [
        ["" if i >= len(r) or is_null(r[i]) else r[i] for r in sample] for i in range(width)
    ]
    chosen_locale = locale or detect_locale(col_values)
    engine = TypeInferenceEngine(locale=chosen_locale, max_sample=INFERENCE_SAMPLE)

    columns: list[ColumnProposal] = []
    for i, values in enumerate(col_values):
        non_empty = [v for v in values if v.strip()]
        null_ratio = 1 - len(non_empty) / len(values) if values else 1.0
        distinct_ratio = len(set(non_empty)) / len(non_empty) if non_empty else 0.0
        notes: list[str] = []
        col_locale = chosen_locale
        inferred = engine.infer_column(names[i], values)
        specific = next((c for c in inferred.candidates if c.type_name != "string"), None)
        best = inferred.best_candidate()
        ambiguous = inferred.is_ambiguous
        if specific is not None and specific.confidence >= 0.5:
            # Propose the most plausible specific type. If any value fails to
            # parse, those rows would be quarantined, so a person must decide.
            best = specific
            ambiguous = specific.confidence < 1.0
        type_name = best.type_name if best else "string"
        if type_name in ("integer", "float") and any(
            len(v.strip()) > 1 and v.strip()[0] == "0" and v.strip()[1].isdigit() for v in non_empty
        ):
            # Codes like ZIPs, phone numbers and account numbers: keep leading zeros.
            type_name, ambiguous = "string", False
            best = next((c for c in inferred.candidates if c.type_name == "string"), best)
            notes.append("Leading zeros found; kept as text so codes are not altered")
        if type_name == "date":
            order = date_order(non_empty)
            if order == "dmy" and chosen_locale == "en_US":
                col_locale = "en_GB"
                notes.append("Day-first dates detected")
            elif order == "mdy" and chosen_locale != "en_US":
                col_locale = "en_US"
                notes.append("Month-first dates detected")
        if ambiguous and best is not None:
            notes.append(
                f"Only {best.confidence:.0%} of values parse as {best.type_name}; "
                "choose a type or the rest will be quarantined"
            )
        role = suggest_role(names[i], type_name, distinct_ratio)
        columns.append(
            ColumnProposal(
                index=i,
                source_name=header_cells[i].strip() if i < len(header_cells) else "",
                name=names[i],
                type=type_name,
                locale=col_locale,
                role=role.value,
                nullable=True,
                ambiguous=ambiguous,
                null_ratio=round(null_ratio, 4),
                distinct_ratio=round(distinct_ratio, 4),
                candidates=[
                    {
                        "type": c.type_name,
                        "confidence": c.confidence,
                        "samples": c.sample_values[:3],
                        "failures": c.failure_samples[:3],
                    }
                    for c in inferred.candidates
                ],
                notes=notes,
            )
        )

    preview = [[r[i] if i < len(r) else "" for i in range(width)] for r in data_rows[:PREVIEW_ROWS]]
    return ImportProposal(
        header_row=header_idx,
        data_start_row=start,
        locale=chosen_locale,
        confidence=confidence,
        columns=columns,
        preview=preview,
        row_estimate=len(data_rows),
        warnings=warns,
        sheet=sheet,
        delimiter=delimiter,
        encoding=encoding,
    )
