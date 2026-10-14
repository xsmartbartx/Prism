"""Tests for the SVG Renderer."""
from __future__ import annotations

from presentation.render.svg_renderer import SvgRenderer, _to_num, _yrange, _ticks
from presentation.spec.view_spec import (
    Encoding,
    EncodingChannel,
    MarkType,
    ViewSpec,
)


class TestSvgRenderer:
    def setup_method(self) -> None:
        self.renderer = SvgRenderer()

    def test_empty_chart(self):
        spec = ViewSpec(
            mark=MarkType.BAR,
            encodings=[Encoding(channel=EncodingChannel.X, field="x")],
        )
        svg = self.renderer.render(spec, [])
        assert "No data" in svg
        assert "<svg" in svg
        assert "</svg>" in svg

    def test_empty_on_none(self):
        spec = ViewSpec(
            mark=MarkType.TABLE,
            encodings=[Encoding(channel=EncodingChannel.X, field="x")],
        )
        svg = self.renderer.render(spec, [])
        assert "No data" in svg

    def test_table_output(self):
        spec = ViewSpec(
            mark=MarkType.TABLE,
            encodings=[
                Encoding(channel=EncodingChannel.X, field="name"),
                Encoding(channel=EncodingChannel.Y, field="age"),
            ],
        )
        rows = [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]
        svg = self.renderer.render(spec, rows)
        assert "<svg" in svg
        assert "Alice" in svg
        assert "Bob" in svg
        assert "30" in svg
        assert "25" in svg

    def test_bar_output(self):
        spec = ViewSpec(
            mark=MarkType.BAR,
            encodings=[
                Encoding(channel=EncodingChannel.X, field="cat"),
                Encoding(channel=EncodingChannel.Y, field="val"),
            ],
        )
        rows = [{"cat": "A", "val": 10}, {"cat": "B", "val": 20}]
        svg = self.renderer.render(spec, rows)
        assert "<svg" in svg
        assert '<rect ' in svg
        assert 'stroke="#eee"' in svg or 'stroke="#e' in svg


class TestPureFunctions:
    def test_to_num_int(self) -> None:
        assert _to_num(42) == 42.0

    def test_to_num_float(self) -> None:
        assert _to_num(3.14) == 3.14

    def test_to_num_string(self) -> None:
        assert _to_num("100") == 100.0

    def test_to_num_none(self) -> None:
        assert _to_num(None) == 0.0

    def test_to_num_currency(self) -> None:
        assert _to_num("$1,234.56") == 1234.56

    def test_to_num_invalid(self) -> None:
        assert _to_num("hello") == 0.0

    def test_yrange_basic(self) -> None:
        lo, hi = _yrange([10, 20, 30])
        assert lo < 10
        assert hi > 30

    def test_yrange_single(self) -> None:
        lo, hi = _yrange([100])
        assert lo < 100 < hi

    def test_yrange_zero(self) -> None:
        lo, hi = _yrange([0])
        assert lo <= 0 < hi

    def test_yrange_empty(self) -> None:
        lo, hi = _yrange([])
        assert lo == 0
        assert hi == 1

    def test_ticks_basic(self) -> None:
        ticks = _ticks(0, 100, 5)
        assert len(ticks) >= 5
        assert ticks[0] <= 0
        assert ticks[-1] >= 100