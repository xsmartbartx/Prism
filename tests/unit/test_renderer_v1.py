"""Renderer v1: every mark, accessibility, determinism, formatting, validation."""

from __future__ import annotations

import re
from datetime import date
from xml.etree import ElementTree

import pytest

from presentation.render.format import format_category, format_number
from presentation.render.svg_renderer import SvgRenderer
from presentation.spec.view_spec import (
    Encoding,
    EncodingChannel,
    MarkType,
    NumberFormat,
    Orientation,
    ViewSpec,
    validate_view,
)

X, Y, C = EncodingChannel.X, EncodingChannel.Y, EncodingChannel.COLOR
ROWS = [
    {"m": date(2026, 1, 1), "region": "EU", "rev": 100.0},
    {"m": date(2026, 1, 1), "region": "US", "rev": 150.0},
    {"m": date(2026, 2, 1), "region": "EU", "rev": 120.0},
    {"m": date(2026, 2, 1), "region": "US", "rev": None},
]


def spec(mark: MarkType, *encs: Encoding, **kw: object) -> ViewSpec:
    return ViewSpec(mark=mark, encodings=list(encs), **kw)  # type: ignore[arg-type]


ALL = [
    spec(MarkType.BAR, Encoding(channel=X, field="m"), Encoding(channel=Y, field="rev"), Encoding(channel=C, field="region")),
    spec(MarkType.BAR, Encoding(channel=X, field="region"), Encoding(channel=Y, field="rev"), orientation=Orientation.HORIZONTAL, show_values=True),
    spec(MarkType.BAR, Encoding(channel=X, field="m"), Encoding(channel=Y, field="rev"), Encoding(channel=C, field="region"), stacked=True),
    spec(MarkType.LINE, Encoding(channel=X, field="m"), Encoding(channel=Y, field="rev"), Encoding(channel=C, field="region"), time_grain="month"),
    spec(MarkType.AREA, Encoding(channel=X, field="m"), Encoding(channel=Y, field="rev"), Encoding(channel=C, field="region"), stacked=True),
    spec(MarkType.SCATTER, Encoding(channel=X, field="rev"), Encoding(channel=Y, field="rev"), Encoding(channel=C, field="region")),
    spec(MarkType.PIE, Encoding(channel=X, field="region"), Encoding(channel=Y, field="rev")),
    spec(MarkType.KPI, Encoding(channel=Y, field="rev", label="Revenue"), number_format=NumberFormat.CURRENCY),
    spec(MarkType.TABLE, Encoding(channel=X, field="region"), Encoding(channel=Y, field="rev")),
]


@pytest.mark.parametrize("view", ALL, ids=lambda v: f"{v.mark.value}")
def test_every_mark_is_valid_accessible_svg(view: ViewSpec) -> None:
    svg = SvgRenderer().render(view, ROWS)
    root = ElementTree.fromstring(svg)  # well-formed XML
    assert root.get("role") == "img"
    ns = "{http://www.w3.org/2000/svg}"
    assert root.find(f"{ns}title") is not None and root.find(f"{ns}desc") is not None
    assert not re.search(r"\bnan\b|\binf\b", svg.lower())


@pytest.mark.parametrize("view", ALL, ids=lambda v: f"{v.mark.value}")
def test_rendering_is_deterministic(view: ViewSpec) -> None:
    r = SvgRenderer()
    assert r.render(view, ROWS) == r.render(view, ROWS)


def test_marks_have_value_tooltips() -> None:
    svg = SvgRenderer().render(ALL[0], ROWS)
    assert "EU: 100" in svg and "US: 150" in svg


def test_dark_theme_and_title_escaping() -> None:
    view = spec(MarkType.BAR, Encoding(channel=X, field="region"), Encoding(channel=Y, field="rev"), theme="dark", title="<b>Rev & Co</b>")
    svg = SvgRenderer().render(view, ROWS)
    assert "#0d1117" in svg
    assert "&lt;b&gt;Rev &amp; Co&lt;/b&gt;" in svg and "<b>" not in svg


def test_bars_include_zero_baseline() -> None:
    rows = [{"k": "a", "v": 1000.0}, {"k": "b", "v": 1010.0}]
    svg = SvgRenderer().render(spec(MarkType.BAR, Encoding(channel=X, field="k"), Encoding(channel=Y, field="v")), rows)
    assert ">0</text>" in svg


def test_pie_groups_small_slices_into_other() -> None:
    rows = [{"k": f"c{i}", "v": float(20 - i)} for i in range(12)]
    svg = SvgRenderer().render(spec(MarkType.PIE, Encoding(channel=X, field="k"), Encoding(channel=Y, field="v")), rows)
    assert "Other" in svg
    assert len(re.findall(r"<path ", svg)) == 8


def test_year_integers_are_not_grouped() -> None:
    rows = [{"year": 2025, "v": 1}, {"year": 2026, "v": 2}]
    svg = SvgRenderer().render(spec(MarkType.BAR, Encoding(channel=X, field="year"), Encoding(channel=Y, field="v")), rows)
    assert ">2026<" in svg and "2,026" not in svg


@pytest.mark.parametrize(
    ("value", "fmt", "kw", "expected"),
    [
        (1234.5, NumberFormat.AUTO, {}, "1,234.5"),
        (1234.5, NumberFormat.AUTO, {"locale": "de_DE"}, "1.234,5"),
        (0.256, NumberFormat.PERCENT, {}, "25.6%"),
        (2_500_000, NumberFormat.COMPACT, {}, "2.5M"),
        (19.99, NumberFormat.CURRENCY, {"currency": "EUR", "locale": "de_DE"}, "19,99\xa0€"),
        (None, NumberFormat.AUTO, {}, "–"),
        (3.0, NumberFormat.INTEGER, {}, "3"),
    ],
)
def test_format_number(value: object, fmt: NumberFormat, kw: dict[str, str], expected: str) -> None:
    assert format_number(value, fmt, **kw) == expected


def test_format_category_by_grain() -> None:
    d = date(2026, 5, 1)
    assert format_category(d, time_grain="month") == "May 2026"
    assert format_category(d, time_grain="quarter") == "Q2 2026"
    assert format_category(d, time_grain="year") == "2026"
    assert format_category("2026-05-01", time_grain="month") == "May 2026"
    assert format_category(None) == "(blank)"


class TestValidateView:
    def test_ok(self) -> None:
        assert validate_view(ALL[0], ["m", "rev", "region"]) == []

    def test_missing_output_field(self) -> None:
        errs = validate_view(ALL[0], ["m", "rev"])
        assert any("region" in e for e in errs)

    def test_required_channels(self) -> None:
        v = spec(MarkType.LINE, Encoding(channel=X, field="m"))
        assert any("needs a y" in e for e in validate_view(v, ["m"]))
        p = spec(MarkType.PIE, Encoding(channel=Y, field="rev"))
        assert any("color or x" in e for e in validate_view(p, ["rev"]))

    def test_multi_y_and_color_conflict(self) -> None:
        v = spec(MarkType.BAR, Encoding(channel=X, field="m"), Encoding(channel=Y, field="a"), Encoding(channel=Y, field="b"), Encoding(channel=C, field="c"))
        assert any("not both" in e for e in validate_view(v, ["m", "a", "b", "c"]))
