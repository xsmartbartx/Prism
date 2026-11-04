"""Deterministic chart recommendation rules.

Given the fields a person picked (with their types, roles and a rough
cardinality), propose a query spec and a view spec that answer the
obvious question correctly. The rules prefer the honest chart: bars
from zero for comparisons, lines for time, a table when nothing else
fits. They never guess at semantics the column contract does not state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from data.query.spec import AggFunction, AggregationSpec, QuerySpec, SortDir, SortSpec, TimeGrain
from presentation.spec.view_spec import (
    Encoding,
    EncodingChannel,
    MarkType,
    Orientation,
    ViewSpec,
)


@dataclass(frozen=True)
class FieldInfo:
    name: str
    type: str  # integer | float | string | date | boolean
    role: str  # dimension | measure | identifier | time | geography | metadata
    distinct: int | None = None
    date_span_days: int | None = None


@dataclass
class Recommendation:
    query: QuerySpec
    view: ViewSpec
    reason: str
    alternatives: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query.model_dump(mode="json"),
            "view": self.view.model_dump(mode="json"),
            "reason": self.reason,
            "alternatives": self.alternatives,
        }


def _is_measure(f: FieldInfo) -> bool:
    return f.role == "measure" and f.type in ("integer", "float")


def _is_time(f: FieldInfo) -> bool:
    return f.type == "date" or (f.role == "time" and f.type == "integer")


def _grain(f: FieldInfo) -> TimeGrain | None:
    if f.type != "date":
        return None
    span = f.date_span_days or 0
    if span > 365 * 6:
        return TimeGrain.YEAR
    if span > 365 * 2:
        return TimeGrain.QUARTER
    if span > 92:
        return TimeGrain.MONTH
    if span > 21:
        return TimeGrain.WEEK
    return TimeGrain.DAY


def _measure(f: FieldInfo) -> AggregationSpec:
    return AggregationSpec(column=f.name, function=AggFunction.SUM)


def recommend(fields: list[FieldInfo], *, title: str | None = None) -> Recommendation:
    """Recommend a (query, view) pair for the selected fields."""
    if not fields:
        raise ValueError("Select at least one field")
    measures = [f for f in fields if _is_measure(f)]
    times = [f for f in fields if _is_time(f) and not _is_measure(f)]
    dims = [
        f
        for f in fields
        if not _is_measure(f) and not _is_time(f) and f.role not in ("identifier", "metadata")
    ]
    ids = [f for f in fields if f.role == "identifier"]

    def view(mark: MarkType, encs: list[Encoding], **kw: Any) -> ViewSpec:
        return ViewSpec(mark=mark, encodings=encs, title=title, **kw)

    x, y, color = EncodingChannel.X, EncodingChannel.Y, EncodingChannel.COLOR

    # No measure at all: count rows per dimension, or show a table.
    if not measures:
        group = (times or dims)[:1]
        if group:
            g = group[0]
            grain = _grain(g)
            q = QuerySpec(
                dimensions=[g.name],
                measures=[AggregationSpec(column="*", function=AggFunction.COUNT, alias="count")],
                time_grain={g.name: grain} if grain else {},
                sort=[SortSpec(column=g.name)]
                if times
                else [SortSpec(column="count", direction=SortDir.DESC)],
                limit=500 if times else 25,
            )
            mark = MarkType.LINE if times else MarkType.BAR
            orient = (
                Orientation.HORIZONTAL
                if not times and (g.distinct or 0) > 8
                else Orientation.VERTICAL
            )
            return Recommendation(
                q,
                view(
                    mark,
                    [
                        Encoding(channel=x, field=g.name),
                        Encoding(channel=y, field="count", label="Rows"),
                    ],
                    time_grain=grain.value if grain else None,
                    orientation=orient,
                ),
                f"Counting rows by {g.name}",
                ["table"],
            )
        cols = [f.name for f in fields]
        return Recommendation(
            QuerySpec(columns=cols, limit=200),
            view(MarkType.TABLE, [Encoding(channel=x, field=c) for c in cols]),
            "No measure selected: showing rows",
        )

    # Measures only: KPI (one) or scatter over raw rows (two).
    if not times and not dims:
        if len(measures) == 2 and ids:
            m1, m2 = measures
            return Recommendation(
                QuerySpec(columns=[ids[0].name, m1.name, m2.name], limit=5000),
                view(
                    MarkType.SCATTER,
                    [Encoding(channel=x, field=m1.name), Encoding(channel=y, field=m2.name)],
                ),
                f"Relationship between {m1.name} and {m2.name}",
                ["kpi"],
            )
        m = measures[0]
        return Recommendation(
            QuerySpec(measures=[_measure(m)]),
            view(
                MarkType.KPI,
                [Encoding(channel=y, field=m.name, label=f"Total {m.name}")],
                width=320,
                height=160,
            ),
            f"Single total of {m.name}",
            ["bar", "table"],
        )

    # Time on x: line (multi-series by a low-cardinality dimension).
    if times:
        t = times[0]
        grain = _grain(t)
        series = next((d for d in dims if (d.distinct or 99) <= 10), None)
        dims_q = [t.name] + ([series.name] if series else [])
        q = QuerySpec(
            dimensions=dims_q,
            measures=[_measure(m) for m in measures[: 1 if series else 4]],
            time_grain={t.name: grain} if grain else {},
            sort=[SortSpec(column=t.name)],
            limit=5000,
        )
        encs = [Encoding(channel=x, field=t.name)] + [
            Encoding(channel=y, field=m.name) for m in measures[: 1 if series else 4]
        ]
        if series:
            encs.append(Encoding(channel=color, field=series.name))
        return Recommendation(
            q,
            view(MarkType.LINE, encs, time_grain=grain.value if grain else None),
            f"{measures[0].name} over time" + (f" by {series.name}" if series else ""),
            ["area", "bar", "table"],
        )

    # Categorical comparison.
    d = dims[0]
    second = dims[1] if len(dims) > 1 and (dims[1].distinct or 99) <= 10 else None
    if second:
        q = QuerySpec(
            dimensions=[d.name, second.name],
            measures=[_measure(measures[0])],
            sort=[SortSpec(column=measures[0].name, direction=SortDir.DESC)],
            limit=1000,
        )
        return Recommendation(
            q,
            view(
                MarkType.BAR,
                [
                    Encoding(channel=x, field=d.name),
                    Encoding(channel=y, field=measures[0].name),
                    Encoding(channel=color, field=second.name),
                ],
                stacked=True,
            ),
            f"{measures[0].name} by {d.name}, split by {second.name}",
            ["table"],
        )
    q = QuerySpec(
        dimensions=[d.name],
        measures=[_measure(m) for m in measures[:3]],
        sort=[SortSpec(column=measures[0].name, direction=SortDir.DESC)],
        limit=25,
    )
    many = (d.distinct or 0) > 8
    alts = ["table"]
    if len(measures) == 1 and (d.distinct or 99) <= 6:
        alts.insert(0, "pie")
    return Recommendation(
        q,
        view(
            MarkType.BAR,
            [Encoding(channel=x, field=d.name)]
            + [Encoding(channel=y, field=m.name) for m in measures[:3]],
            orientation=Orientation.HORIZONTAL if many else Orientation.VERTICAL,
        ),
        f"Comparing {measures[0].name} across {d.name}",
        alts,
    )
