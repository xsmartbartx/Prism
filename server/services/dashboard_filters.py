"""Dashboard filters: one control, every tile.

An author declares filters on a dashboard by field name; a viewer picks values. Every tile
whose dataset has a column of that name (ignoring case and spacing, so "Region" in one file
matches "region" in another) gets an extra, bound predicate ANDed onto its own
query, so a filter can only ever narrow what a tile already shows. A tile whose dataset lacks
the field (or holds it with a type the selection cannot be read as) is left unfiltered and
says so, rather than silently showing numbers for a different slice.

Selections travel as plain query parameters, indexed by the filter's position, so the same
encoding works for the app's API and for a share page's HTML form without JavaScript:

    fv<i>=<value>   (repeatable)   a "values" filter: keep rows whose field is one of these
    ff<i>=<date>    ft<i>=<date>   a "date_range" filter: from / to, inclusive, ISO dates

A cross-filter is what clicking a bar, slice or point in one tile sets: the same kind of
narrowing, on any field, without a declared filter. It applies to every tile except the one
that was clicked (which highlights the choice instead):

    xf=<field>  xv=<value> (repeatable)  [xg=<time grain>]  xc=<chart id of the clicked tile>

With ``xg`` the value is the first day of a calendar bucket (a month bar, say) and the
cross-filter becomes that bucket's date range.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from data.query import QuerySpec
from data.query.compiler import coerce_filter_value
from data.query.spec import FilterOp, FilterSpec
from server.errors import BadRequest

MAX_FILTERS = 6
MAX_SELECTED = 100
MAX_VALUE_CHARS = 200
VALUE_LIMIT = 200  # distinct values offered in a picker
KINDS = ("values", "date_range")
VALUE_TYPES = {"string", "integer", "boolean", "date"}


def field_key(name: str) -> str:
    """How field names are matched across datasets: case- and whitespace-insensitive."""
    return " ".join(name.split()).casefold()


def resolve_column(field: str, column_types: dict[str, str]) -> str | None:
    """The column in one dataset that a dashboard field refers to, if any."""
    if field in column_types:
        return field
    key = field_key(field)
    return next((c for c in column_types if field_key(c) == key), None)


@dataclass(frozen=True)
class Selection:
    """What a viewer picked for one declared filter."""

    index: int
    field: str
    kind: str
    label: str
    values: tuple[str, ...] = ()
    start: date | None = None
    end: date | None = None


def clean_definitions(
    raw: Iterable[dict[str, Any]], available: dict[str, set[str]]
) -> list[dict[str, str]]:
    """Validate an author's filter list against the fields the dashboard's tiles have.

    ``available`` maps each column name found in the tiles' datasets to the set of types it
    has there; names are matched with :func:`field_key`.
    """
    by_key: dict[str, set[str]] = {}
    for name, name_types in available.items():
        by_key.setdefault(field_key(name), set()).update(name_types)
    items = list(raw)
    if len(items) > MAX_FILTERS:
        raise BadRequest(f"A dashboard holds at most {MAX_FILTERS} filters")
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        field = str(item.get("field", "")).strip()
        kind = str(item.get("kind", "values"))
        label = str(item.get("label") or field).strip()[:80] or field
        if not field:
            raise BadRequest("Each filter needs a field")
        if field_key(field) in seen:
            raise BadRequest(f"'{field}' is filtered twice")
        if kind not in KINDS:
            raise BadRequest(f"Unknown filter kind '{kind}'")
        types = by_key.get(field_key(field))
        if not types:
            raise BadRequest(f"No chart on this dashboard has a field named '{field}'")
        if kind == "date_range" and "date" not in types:
            raise BadRequest(f"'{field}' is not a date, so it cannot have a date range")
        if kind == "values" and not types & VALUE_TYPES:
            raise BadRequest(f"'{field}' holds decimals; pick values from a text or date field")
        seen.add(field_key(field))
        out.append({"field": field, "kind": kind, "label": label})
    return out


def _iso_date(text: str | None) -> date | None:
    if not text:
        return None
    try:
        return date.fromisoformat(text.strip()[:10])
    except ValueError:
        return None


def parse_selections(
    definitions: list[dict[str, Any]], params: Iterable[tuple[str, str]]
) -> list[Selection]:
    """Read ``fv<i>`` / ``ff<i>`` / ``ft<i>`` parameters into selections (empty ones dropped).

    Anything malformed — an unknown index, an unreadable date, an over-long value — is
    ignored rather than rejected: a stale or hand-edited link still shows the dashboard.
    """
    values: dict[int, list[str]] = {}
    starts: dict[int, str] = {}
    ends: dict[int, str] = {}
    for key, value in params:
        suffix = key[2:]
        # ASCII digits only: str.isdigit() also accepts characters like "²" that int() rejects.
        if key[:2] not in ("fv", "ff", "ft") or not (suffix.isascii() and suffix.isdigit()):
            continue
        i = int(suffix)
        if i >= len(definitions):
            continue
        if key.startswith("fv"):
            v = value.strip()
            if v and len(v) <= MAX_VALUE_CHARS:
                bucket = values.setdefault(i, [])
                if v not in bucket and len(bucket) < MAX_SELECTED:
                    bucket.append(v)
        elif key.startswith("ff"):
            starts[i] = value
        else:
            ends[i] = value

    out: list[Selection] = []
    for i, d in enumerate(definitions):
        field, kind = d["field"], d["kind"]
        label = d.get("label") or field
        if kind == "values" and values.get(i):
            out.append(Selection(i, field, kind, label, values=tuple(values[i])))
        elif kind == "date_range":
            start, end = _iso_date(starts.get(i)), _iso_date(ends.get(i))
            if start and end and start > end:
                start, end = end, start
            if start or end:
                out.append(Selection(i, field, kind, label, start=start, end=end))
    return out


GRAINS = ("day", "week", "month", "quarter", "year")
CROSS = -1  # Selection.index of a cross-filter (it belongs to no declared filter)


def bucket_end(start: date, grain: str) -> date:
    """The last day of the calendar bucket that starts on ``start``."""
    if grain == "week":
        return start + timedelta(days=6)
    if grain in ("month", "quarter"):
        month = start.month + (2 if grain == "quarter" else 0)
        year = start.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        return date(year, month, calendar.monthrange(year, month)[1])
    if grain == "year":
        return date(start.year, 12, 31)
    return start


def _read_cross(params: Iterable[tuple[str, str]]) -> tuple[str, str, str | None, list[str]]:
    field, grain, source = "", "", None
    values: list[str] = []
    for key, value in params:
        if key == "xf":
            field = value.strip()
        elif key == "xg":
            grain = value.strip()
        elif key == "xc":
            source = value.strip() or None
        elif key == "xv":
            v = value.strip()
            if v and len(v) <= MAX_VALUE_CHARS and v not in values and len(values) < MAX_SELECTED:
                values.append(v)
    return field, grain, source, values


def parse_cross_filter(params: Iterable[tuple[str, str]]) -> tuple[Selection | None, str | None]:
    """Read ``xf`` / ``xv`` / ``xg`` / ``xc`` into a selection and the clicked chart's id.

    Like declared filters, anything malformed is ignored: the dashboard still shows.
    """
    field, grain, source, values = _read_cross(params)
    if not field or len(field) > MAX_VALUE_CHARS or not values:
        return None, source
    if grain not in GRAINS:
        return Selection(CROSS, field, "values", field, values=tuple(values)), source
    starts = sorted(d for d in (_iso_date(v) for v in values) if d)
    if not starts:
        return None, source
    end = bucket_end(starts[-1], grain)
    return Selection(CROSS, field, "date_range", field, start=starts[0], end=end), source


def apply_selections(
    spec: QuerySpec, column_types: dict[str, str], selections: list[Selection]
) -> tuple[QuerySpec, list[str], list[str]]:
    """AND the selections onto a tile's query.

    Returns the narrowed query, the labels of filters applied, and the labels of filters
    that could not apply to this tile (field missing, or of a type the selection cannot be
    read as).
    """
    extra: list[FilterSpec] = []
    applied: list[str] = []
    skipped: list[str] = []
    for sel in selections:
        column = resolve_column(sel.field, column_types)
        if column is None:
            skipped.append(sel.label)
            continue
        col_type = column_types[column]
        if sel.kind == "values":
            if col_type not in VALUE_TYPES:
                skipped.append(sel.label)
                continue
            kept = []
            for v in sel.values:
                try:
                    coerce_filter_value(v, col_type)
                except (TypeError, ValueError):
                    continue
                kept.append(v)
            if not kept:
                skipped.append(sel.label)
                continue
            extra.append(FilterSpec(column=column, operator=FilterOp.IN, value=kept))
        else:
            if col_type != "date":
                skipped.append(sel.label)
                continue
            if sel.start:
                extra.append(
                    FilterSpec(column=column, operator=FilterOp.GTE, value=sel.start.isoformat())
                )
            if sel.end:
                extra.append(
                    FilterSpec(column=column, operator=FilterOp.LTE, value=sel.end.isoformat())
                )
        applied.append(sel.label)
    if not extra:
        return spec, applied, skipped
    return spec.model_copy(update={"filters": [*spec.filters, *extra]}), applied, skipped


def encode_selections(selections: list[Selection]) -> list[tuple[str, str]]:
    """The query parameters that reproduce these selections (for links and forms)."""
    out: list[tuple[str, str]] = []
    for sel in selections:
        out += [(f"fv{sel.index}", v) for v in sel.values]
        if sel.start:
            out.append((f"ff{sel.index}", sel.start.isoformat()))
        if sel.end:
            out.append((f"ft{sel.index}", sel.end.isoformat()))
    return out
