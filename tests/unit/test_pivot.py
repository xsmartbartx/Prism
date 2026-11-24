"""Pivot tables: rows × columns → one value, with totals only where they are right."""

from __future__ import annotations

import re

import pytest

from data.query import QuerySpec
from data.query.spec import AggFunction, AggregationSpec
from presentation.render.svg_renderer import SvgRenderer
from presentation.spec.view_spec import Encoding, EncodingChannel, MarkType, ViewSpec, validate_view
from server.services.artifacts import _pivot_totals

X = Encoding(channel=EncodingChannel.X, field="Region")
C = Encoding(channel=EncodingChannel.COLOR, field="Channel")
Y = Encoding(channel=EncodingChannel.Y, field="Revenue")
ROWS = [
    {"Region": "EU", "Channel": "Online", "Revenue": 10.0},
    {"Region": "EU", "Channel": "Retail", "Revenue": 5.0},
    {"Region": "US", "Channel": "Online", "Revenue": 7.0},
]


def texts(svg: str) -> list[str]:
    return re.findall(r">([^<>]+)</text>", svg)


def render(**kw: object) -> str:
    spec = ViewSpec(mark=MarkType.PIVOT, encodings=[X, C, Y], **kw)  # type: ignore[arg-type]
    return SvgRenderer().render(spec, ROWS)


def test_cells_headers_and_totals() -> None:
    t = texts(render(total_function="sum"))
    assert t[:4] == ["Region / Channel", "Online", "Retail", "Total"]
    assert t[4:8] == ["EU", "10", "5", "15"]
    assert t[8:12] == ["US", "7", "–", "7"]  # no Retail sales in the US: an empty cell
    assert t[12:] == ["Total", "17", "5", "22"]


@pytest.mark.parametrize(("fn", "eu", "grand"), [("min", "5", "5"), ("max", "10", "10")])
def test_min_and_max_totals(fn: str, eu: str, grand: str) -> None:
    t = texts(render(total_function=fn))
    assert t[7] == eu and t[-1] == grand


def test_no_totals_when_they_would_be_wrong_or_are_off() -> None:
    for kw in ({}, {"total_function": "sum", "totals": False}):
        t = texts(render(**kw))
        assert "Total" not in t, kw


def test_heat_map_shades_cells_only_when_asked() -> None:
    plain, shaded = render(total_function="sum"), render(total_function="sum", heatmap=True)
    assert "fill-opacity" not in plain
    opacities = [float(o) for o in re.findall(r'fill-opacity="([0-9.]+)"', shaded)]
    assert len(opacities) == 3 and min(opacities) == pytest.approx(0.08) and max(opacities) == pytest.approx(0.58)


def test_rows_pick_for_click_to_filter_and_text_is_escaped() -> None:
    rows = [{"Region": "<b>&", "Channel": "Online", "Revenue": 1.0}]
    svg = SvgRenderer().render(ViewSpec(mark=MarkType.PIVOT, encodings=[X, C, Y]), rows)
    assert 'data-pick-field="Region"' in svg and 'data-pick="&lt;b&gt;&amp;"' in svg
    assert "<b>" not in svg


def test_without_columns_and_with_caps() -> None:
    single = texts(SvgRenderer().render(
        ViewSpec(mark=MarkType.PIVOT, encodings=[X, Y], total_function="sum"), ROWS
    ))
    assert single[:3] == ["Region", "Revenue", "EU"] and "Total" in single
    many = [{"Region": f"R{i}", "Channel": f"C{j}", "Revenue": 1.0} for i in range(3) for j in range(25)]
    t = texts(SvgRenderer().render(ViewSpec(mark=MarkType.PIVOT, encodings=[X, C, Y]), many))
    assert "Showing the first 20 columns" in t and "C20" not in t


def test_view_checks() -> None:
    spec = ViewSpec(mark=MarkType.PIVOT, encodings=[X])
    assert any("needs a y encoding" in e for e in validate_view(spec, []))
    two = ViewSpec(mark=MarkType.PIVOT, encodings=[X, Y, Encoding(channel=EncodingChannel.Y, field="Cost")])
    assert any("one value" in e for e in validate_view(two, []))


@pytest.mark.parametrize(
    ("function", "expected"),
    [
        (AggFunction.SUM, "sum"),
        (AggFunction.COUNT, "sum"),
        (AggFunction.MIN, "min"),
        (AggFunction.MAX, "max"),
        (AggFunction.AVG, None),
        (AggFunction.MEDIAN, None),
        (AggFunction.COUNT_DISTINCT, None),
        (AggFunction.VALUE, None),
    ],
)
def test_totals_follow_the_aggregation(function: AggFunction, expected: str | None) -> None:
    q = QuerySpec(dimensions=["Region"], measures=[AggregationSpec(column="Revenue", function=function)])
    assert _pivot_totals(q) == expected
