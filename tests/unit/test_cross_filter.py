"""Cross-filtering: clickable marks in the SVG, and reading a click back as a selection."""

from __future__ import annotations

import re
from datetime import date, datetime

import pytest

from presentation.render.svg_renderer import SvgRenderer, pick_value
from presentation.spec.view_spec import Encoding, EncodingChannel, MarkType, ViewSpec
from server.services.dashboard_filters import (
    CROSS,
    MAX_SELECTED,
    bucket_end,
    parse_cross_filter,
)

X = Encoding(channel=EncodingChannel.X, field="Region")
Y = Encoding(channel=EncodingChannel.Y, field="Revenue")
ROWS = [{"Region": "EU", "Revenue": 10.0}, {"Region": 'A&B "Co"', "Revenue": 5.0}]


def _picks(svg: str) -> list[str]:
    return re.findall(r'class="pick" data-pick="([^"]*)"', svg)


class TestMarks:
    @pytest.mark.parametrize("mark", [MarkType.BAR, MarkType.LINE, MarkType.AREA, MarkType.PIE])
    def test_marks_carry_their_category(self, mark: MarkType) -> None:
        svg = SvgRenderer().render(ViewSpec(mark=mark, encodings=[X, Y]), ROWS)
        assert 'data-pick-field="Region"' in svg
        assert set(_picks(svg)) == {"EU", "A&amp;B &quot;Co&quot;"}  # escaped like all text
        assert "data-pick-grain" not in svg

    def test_time_buckets_say_their_grain(self) -> None:
        spec = ViewSpec(
            mark=MarkType.BAR,
            time_grain="month",
            encodings=[Encoding(channel=EncodingChannel.X, field="Month"), Y],
        )
        rows = [{"Month": date(2026, 3, 1), "Revenue": 4.0}]
        svg = SvgRenderer().render(spec, rows)
        assert 'data-pick-grain="month"' in svg and _picks(svg) == ["2026-03-01"]

    def test_no_picks_where_a_mark_is_not_one_category(self) -> None:
        many = [{"Region": f"R{i}", "Revenue": float(10 - i)} for i in range(10)]
        pie = SvgRenderer().render(ViewSpec(mark=MarkType.PIE, encodings=[X, Y]), many)
        assert len(_picks(pie)) == 7  # the "Other" slice holds several regions
        for mark in (MarkType.KPI, MarkType.TABLE, MarkType.SCATTER):
            svg = SvgRenderer().render(ViewSpec(mark=mark, encodings=[X, Y]), ROWS)
            assert "data-pick" not in svg, mark
        none = SvgRenderer().render(
            ViewSpec(mark=MarkType.BAR, encodings=[X, Y]), [{"Region": None, "Revenue": 1.0}]
        )
        assert _picks(none) == []

    def test_raw_values(self) -> None:
        assert pick_value(True) == "true" and pick_value(False) == "false"
        assert pick_value(date(2026, 1, 2)) == "2026-01-02"
        assert pick_value(datetime(2026, 1, 2, 13, 5)) == "2026-01-02"
        assert pick_value(2026.0) == "2026" and pick_value(1.5) == "1.5" and pick_value(7) == "7"
        assert pick_value(None) is None


class TestParse:
    def test_values(self) -> None:
        params = [("xf", " Region "), ("xv", "EU"), ("xv", "US"), ("xv", "EU"), ("xv", " "),
                  ("xc", "chart1"), ("fv0", "x")]
        sel, source = parse_cross_filter(params)
        assert source == "chart1"
        assert sel is not None and (sel.index, sel.field, sel.kind, sel.values) == (
            CROSS, "Region", "values", ("EU", "US"),
        )

    def test_date_buckets_become_ranges(self) -> None:
        sel, _ = parse_cross_filter(
            [("xf", "Order Date"), ("xv", "2026-04-01"), ("xv", "2026-01-01"), ("xg", "quarter")]
        )
        assert sel is not None and sel.kind == "date_range"
        assert (sel.start, sel.end) == (date(2026, 1, 1), date(2026, 6, 30))

    @pytest.mark.parametrize(
        "params",
        [
            [],
            [("xf", "Region")],
            [("xv", "EU")],
            [("xf", "x" * 201), ("xv", "EU")],
            [("xf", "Region"), ("xv", "y" * 201)],
            [("xf", "Order Date"), ("xv", "soon"), ("xg", "month")],
        ],
    )
    def test_junk_is_ignored(self, params: list[tuple[str, str]]) -> None:
        assert parse_cross_filter(params)[0] is None

    def test_value_count_is_capped(self) -> None:
        params = [("xf", "Id"), *[("xv", str(i)) for i in range(MAX_SELECTED + 20)]]
        sel, _ = parse_cross_filter(params)
        assert sel is not None and len(sel.values) == MAX_SELECTED

    def test_unknown_grain_means_plain_values(self) -> None:
        sel, _ = parse_cross_filter([("xf", "Day"), ("xv", "2026-01-05"), ("xg", "fortnight")])
        assert sel is not None and sel.kind == "values" and sel.values == ("2026-01-05",)


@pytest.mark.parametrize(
    ("start", "grain", "end"),
    [
        (date(2026, 3, 9), "day", date(2026, 3, 9)),
        (date(2026, 3, 9), "week", date(2026, 3, 15)),
        (date(2026, 2, 1), "month", date(2026, 2, 28)),
        (date(2028, 2, 1), "month", date(2028, 2, 29)),
        (date(2026, 12, 1), "month", date(2026, 12, 31)),
        (date(2026, 10, 1), "quarter", date(2026, 12, 31)),
        (date(2026, 11, 1), "quarter", date(2027, 1, 31)),  # a misaligned start still ends sanely
        (date(2026, 1, 1), "year", date(2026, 12, 31)),
    ],
)
def test_bucket_end(start: date, grain: str, end: date) -> None:
    assert bucket_end(start, grain) == end
