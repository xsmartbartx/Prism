"""KPI cards over time: the latest complete period, its change, and the trend line."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

import pytest

from data.query import QuerySpec
from data.query.spec import AggFunction, AggregationSpec, TimeGrain
from presentation.render.svg_renderer import SvgRenderer, _period_start, _shift_period
from presentation.spec.view_spec import Encoding, EncodingChannel, MarkType, ViewSpec, validate_view
from server.services.artifacts import _kpi_query_errors

X = Encoding(channel=EncodingChannel.X, field="Month")
Y = Encoding(channel=EncodingChannel.Y, field="Revenue")
# Jan 2025 … Nov 2026, rising by 10 a month; November 2026 is still in progress on 2026-11-27.
MONTHS = [
    {"Month": date(2025 + (m - 1) // 12, (m - 1) % 12 + 1, 1), "Revenue": 100.0 + m * 10}
    for m in range(1, 24)
]


def texts(svg: str) -> list[str]:
    return re.findall(r">([^<>]+)</text>", svg)


def kpi(rows: list[dict[str, Any]] = MONTHS, **kw: Any) -> str:
    spec = ViewSpec(
        mark=MarkType.KPI, encodings=[X, Y], time_grain="month", as_of="2026-11-27",
        width=360, height=180, **kw,
    )
    return SvgRenderer().render(spec, rows)


def test_latest_complete_period_against_the_previous_one() -> None:
    svg = kpi(compare="previous")
    # Nov 2026 (330) is in progress: October (320) is the latest complete month.
    assert texts(svg) == ["Revenue · Oct 2026", "320", "▲ 3.2% vs Sep 2026 (310)"]
    assert "Revenue: 320 in Oct 2026, up 3.2% from 310 in Sep 2026." in svg  # <desc>
    assert 'fill="#1a7f37"' in svg  # a rise is good by default


def test_same_period_last_year_and_rows_in_any_order() -> None:
    svg = kpi(list(reversed(MONTHS)), compare="year")
    assert texts(svg)[2] == "▲ 60% vs Oct 2025 (200)"  # 320 against 200


def test_without_leaving_out_the_current_period() -> None:
    spec = ViewSpec(mark=MarkType.KPI, encodings=[X, Y], time_grain="month", compare="previous")
    assert texts(SvgRenderer().render(spec, MONTHS))[:2] == ["Revenue · Nov 2026", "330"]


def test_lower_is_better_and_falls() -> None:
    falling = [{**r, "Revenue": 1000 - r["Revenue"]} for r in MONTHS]
    svg = kpi(falling, compare="previous", higher_is_better=False)
    assert texts(svg)[2].startswith("▼ 1.4% vs Sep 2026") and 'fill="#1a7f37"' in svg
    svg = kpi(compare="previous", higher_is_better=False)
    assert 'fill="#cf222e"' in svg  # a rise of a cost is bad


def test_percentages_change_in_points_and_zero_bases_in_absolutes() -> None:
    rates = [{"Month": date(2026, 9, 1), "Revenue": 0.25}, {"Month": date(2026, 10, 1), "Revenue": 0.271}]
    svg = kpi(rates, compare="previous", number_format="percent")
    assert texts(svg)[1:] == ["27.1%", "▲ 2.1 pp vs Sep 2026 (25%)"]
    zero = [{"Month": date(2026, 9, 1), "Revenue": 0.0}, {"Month": date(2026, 10, 1), "Revenue": 40.0}]
    assert texts(kpi(zero, compare="previous"))[2] == "▲ 40 vs Sep 2026 (0)"
    same = [{"Month": date(2026, 9, 1), "Revenue": 5.0}, {"Month": date(2026, 10, 1), "Revenue": 5.0}]
    assert texts(kpi(same, compare="previous"))[2] == "No change vs Sep 2026 (5)"


def test_a_missing_period_is_said_not_bridged() -> None:
    gap = [r for r in MONTHS if r["Month"] != date(2026, 9, 1)]
    svg = kpi(gap, compare="previous")
    assert texts(svg)[2] == "No data for Sep 2026 to compare with"
    assert "there is no data for Sep 2026 to compare with." in svg  # screen readers hear it too
    # A latest period without a value shows "–" and blames no other period.
    empty = [{**r, "Revenue": None} if r["Month"] == date(2026, 10, 1) else r for r in MONTHS]
    assert texts(kpi(empty, compare="previous")) == ["Revenue · Oct 2026", "–"]


def test_trend_line() -> None:
    svg = kpi()
    assert svg.count("<polyline") == 1 and "<circle" in svg
    assert len(texts(svg)) == 2  # no comparison asked for: heading and value only
    holed = [{**r, "Revenue": None} if r["Month"] == date(2026, 3, 1) else r for r in MONTHS]
    assert kpi(holed).count("<polyline") == 2  # a period without a value breaks the line
    absent = [r for r in MONTHS if r["Month"] != date(2026, 3, 1)]
    assert kpi(absent).count("<polyline") == 2  # and so does a period without a row
    # ...which keeps its place: the points either side are two steps apart, not one.
    xs = [float(p.split(",")[0]) for p in re.findall(r'points="([^"]+)"', kpi(absent))[0].split()]
    step = xs[1] - xs[0]
    second = [float(p.split(",")[0]) for p in re.findall(r'points="([^"]+)"', kpi(absent))[1].split()]
    assert second[0] - xs[-1] == pytest.approx(2 * step, abs=0.2)
    assert "<polyline" not in kpi(sparkline=False)
    small = ViewSpec(mark=MarkType.KPI, encodings=[X, Y], time_grain="month", height=100)
    assert "<polyline" not in SvgRenderer().render(small, MONTHS)  # no room


def test_dates_as_timestamps_or_text_and_weeks() -> None:
    rows = [
        {"Month": datetime(2026, 10, 5, 0, 0), "Revenue": 7.0},
        {"Month": "2026-10-12", "Revenue": 14.0},
    ]
    spec = ViewSpec(mark=MarkType.KPI, encodings=[X, Y], time_grain="week", compare="previous")
    assert texts(SvgRenderer().render(spec, rows))[0] == "Revenue · Week of Oct 12, 2026"
    assert texts(SvgRenderer().render(spec, rows))[2] == "▲ 100% vs Week of Oct 5, 2026 (7)"


def test_a_plain_kpi_is_unchanged() -> None:
    svg = SvgRenderer().render(ViewSpec(mark=MarkType.KPI, encodings=[Y]), [{"Revenue": 1234.0}])
    assert texts(svg) == ["1,234", "Revenue"] and "<polyline" not in svg


@pytest.mark.parametrize(
    ("d", "grain", "start", "previous", "year"),
    [
        (date(2026, 10, 15), "day", date(2026, 10, 15), date(2026, 10, 14), date(2025, 10, 15)),
        (date(2024, 2, 29), "day", date(2024, 2, 29), date(2024, 2, 28), date(2023, 2, 28)),
        (date(2026, 10, 15), "week", date(2026, 10, 12), date(2026, 10, 5), date(2025, 10, 13)),
        (date(2026, 1, 15), "month", date(2026, 1, 1), date(2025, 12, 1), date(2025, 1, 1)),
        (date(2026, 2, 15), "quarter", date(2026, 1, 1), date(2025, 10, 1), date(2025, 1, 1)),
        (date(2026, 7, 4), "year", date(2026, 1, 1), date(2025, 1, 1), date(2025, 1, 1)),
    ],
)
def test_periods(d: date, grain: str, start: date, previous: date, year: date) -> None:
    s = _period_start(d, grain)
    assert s == start
    assert _shift_period(s, grain, "previous") == previous
    assert _shift_period(s, grain, "year") == year
    if grain == "week":
        assert _shift_period(s, grain, "year").weekday() == 0  # still a Monday


def test_checks() -> None:
    no_date = ViewSpec(mark=MarkType.KPI, encodings=[Y], compare="previous")
    assert any("needs a date field" in e for e in validate_view(no_date, []))
    view = ViewSpec(mark=MarkType.KPI, encodings=[X, Y], compare="previous")
    rev = [AggregationSpec(column="Revenue", function=AggFunction.SUM)]
    ok = QuerySpec(dimensions=["Month"], measures=rev, time_grain={"Month": TimeGrain.MONTH})
    assert _kpi_query_errors(ok, view) == []
    extra = QuerySpec(dimensions=["Month", "Region"], measures=rev, time_grain={"Month": TimeGrain.MONTH})
    assert "groups by its date field (Month) only" in _kpi_query_errors(extra, view)[0]
    no_grain = QuerySpec(dimensions=["Month"], measures=rev)
    assert "Pick a time bucket" in _kpi_query_errors(no_grain, view)[0]
    two = QuerySpec(dimensions=["Month"], measures=[*rev, *rev], time_grain={"Month": TimeGrain.MONTH})
    assert "one value" in _kpi_query_errors(two, view)[0]
    plain = ViewSpec(mark=MarkType.KPI, encodings=[Y])
    assert _kpi_query_errors(QuerySpec(measures=rev), plain) == []
