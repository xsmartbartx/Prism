"""Tests for the ViewSpec schema."""
from __future__ import annotations

from presentation.spec.view_spec import (
    Encoding,
    EncodingChannel,
    MarkType,
    ScaleType,
    ViewSpec,
)


class TestMarkType:
    def test_bar(self) -> None:
        assert MarkType.BAR.value == "bar"

    def test_line(self) -> None:
        assert MarkType.LINE.value == "line"

    def test_table(self) -> None:
        assert MarkType.TABLE.value == "table"


class TestEncoding:
    def test_encoding_requires_field(self) -> None:
        e = Encoding(channel=EncodingChannel.X, field="sales")
        assert e.channel == EncodingChannel.X
        assert e.field == "sales"

    def test_encoding_default_scale(self) -> None:
        e = Encoding(channel=EncodingChannel.Y, field="revenue")
        assert e.scale_type == ScaleType.LINEAR

    def test_encoding_with_label(self) -> None:
        e = Encoding(channel=EncodingChannel.X, field="date", label="Date")
        assert e.label == "Date"


class TestViewSpec:
    def test_minimal_spec(self) -> None:
        spec = ViewSpec(
            mark=MarkType.BAR,
            encodings=[
                Encoding(channel=EncodingChannel.X, field="category"),
                Encoding(channel=EncodingChannel.Y, field="value"),
            ],
        )
        assert spec.mark == MarkType.BAR
        assert len(spec.encodings) == 2

    def test_encoding_for(self) -> None:
        spec = ViewSpec(
            mark=MarkType.BAR,
            encodings=[
                Encoding(channel=EncodingChannel.X, field="category"),
                Encoding(channel=EncodingChannel.Y, field="sales"),
            ],
        )
        x = spec.encoding_for(EncodingChannel.X)
        assert x is not None
        assert x.field == "category"
        y = spec.encoding_for(EncodingChannel.Y)
        assert y is not None
        assert y.field == "sales"
        c = spec.encoding_for(EncodingChannel.COLOR)
        assert c is None

    def test_spec_is_frozen(self) -> None:
        spec = ViewSpec(
            mark=MarkType.TABLE,
            encodings=[
                Encoding(channel=EncodingChannel.X, field="name"),
            ],
        )
        import pydantic
        try:
            spec.title = "New Title"
            assert False, "Should be frozen"
        except pydantic.ValidationError:
            pass
        except TypeError:
            pass  # frozen=True raises TypeError for frozen dataclass-like

    def test_default_dimensions(self) -> None:
        spec = ViewSpec(
            mark=MarkType.BAR,
            encodings=[
                Encoding(channel=EncodingChannel.X, field="cat"),
                Encoding(channel=EncodingChannel.Y, field="val"),
            ],
        )
        assert spec.width == 800
        assert spec.height == 400
        assert spec.title is None