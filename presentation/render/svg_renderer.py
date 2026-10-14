"""SVG Renderer — renders ViewSpec + data into SVG output.

Phase 0 v0: Bar, line, and table charts with SVG output.
Rendering is deterministic: same spec + same data → identical SVG.
"""

from __future__ import annotations

import math
from typing import Any

from presentation.spec.view_spec import EncodingChannel, MarkType, ViewSpec

_COLORS = [
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2",
    "#59a14f", "#edc948", "#b07aa1", "#ff9da7",
]
_MARGIN_TOP = 30
_MARGIN_RIGHT = 20
_MARGIN_BOTTOM = 60
_MARGIN_LEFT = 60


class SvgRenderer:
    """Renders a ViewSpec + data rows into an SVG string."""

    def render(self, spec: ViewSpec, rows: list[dict[str, Any]]) -> str:
        """Render a chart to SVG."""
        if not rows:
            return self._empty_chart(spec)
        mark = spec.mark
        if mark == MarkType.TABLE:
            return self._render_table(spec, rows)
        elif mark == MarkType.BAR:
            return self._render_bar(spec, rows)
        elif mark == MarkType.LINE:
            return self._render_line(spec, rows)
        return self._empty_chart(spec)

    def _render_table(
        self, spec: ViewSpec, rows: list[dict[str, Any]]
    ) -> str:
        x_enc = spec.encoding_for(EncodingChannel.X)
        y_enc = spec.encoding_for(EncodingChannel.Y)
        if x_enc and y_enc:
            columns = [x_enc.field, y_enc.field]
        else:
            columns = list(rows[0].keys()) if rows else []
        cw = min(120, max(60, (spec.width - 2 * _MARGIN_LEFT) // len(columns)))
        rh = 24; hh = 30
        tw = len(columns) * cw
        th = hh + len(rows) * rh
        w = max(spec.width, tw + 2 * _MARGIN_LEFT)
        h = max(spec.height, th + 2 * _MARGIN_TOP)
        out: list[str] = []
        self._svg_header(out, w, h)
        out.append(
            f'<rect x="{_MARGIN_LEFT}" y="{_MARGIN_TOP}" '
            f'width="{tw}" height="{hh}" '
            f'fill="#e8e8e8" stroke="#ccc" stroke-width="1"/>'
        )
        for ci, col in enumerate(columns):
            x = _MARGIN_LEFT + ci * cw
            out.append(
                f'<rect x="{x}" y="{_MARGIN_TOP}" '
                f'width="{cw}" height="{hh}" '
                f'fill="none" stroke="#ccc" stroke-width="1"/>'
            )
            out.append(
                f'<text x="{x + cw / 2}" y="{_MARGIN_TOP + hh / 2}" '
                f'text-anchor="middle" dominant-baseline="central" '
                f'font-size="12" font-weight="bold">'
                f'{self._xml_escape(col)}</text>'
            )
        for ri, row in enumerate(rows):
            y = _MARGIN_TOP + hh + ri * rh
            bg = "#f8f8f8" if ri % 2 == 1 else "#ffffff"
            out.append(
                f'<rect x="{_MARGIN_LEFT}" y="{y}" '
                f'width="{tw}" height="{rh}" '
                f'fill="{bg}" stroke="#ccc" stroke-width="1"/>'
            )
            for ci, col in enumerate(columns):
                vx = _MARGIN_LEFT + ci * cw
                val = row.get(col, "")
                out.append(
                    f'<rect x="{vx}" y="{y}" '
                    f'width="{cw}" height="{rh}" '
                    f'fill="none" stroke="#ccc" stroke-width="1"/>'
                )
                out.append(
                    f'<text x="{vx + 4}" y="{y + rh / 2}" '
                    f'dominant-baseline="central" font-size="11">'
                    f'{self._xml_escape(str(val))}</text>'
                )
        out.append("</svg>")
        return "\n".join(out)
    def _render_bar(
        self, spec: ViewSpec, rows: list[dict[str, Any]]
    ) -> str:
        x_enc = spec.encoding_for(EncodingChannel.X)
        y_enc = spec.encoding_for(EncodingChannel.Y)
        if not x_enc or not y_enc:
            return self._empty_chart(spec)
        cats = [str(row.get(x_enc.field, "")) for row in rows]
        vals = [_to_number(row.get(y_enc.field, 0)) for row in rows]
        n = len(cats)
        w = max(spec.width, 100)
        h = max(spec.height, 100)
        cw = w - _MARGIN_LEFT - _MARGIN_RIGHT
        ch = h - _MARGIN_TOP - _MARGIN_BOTTOM
        y_min, y_max = _compute_y_range(vals)
        band = cw / max(n, 1)
        bar_w = band * 0.7
        out: list[str] = []
        self._svg_header(out, w, h)
        if spec.title:
            out.append(
                f'<text x="{w / 2}" y="{_MARGIN_TOP - 10}" '
                f'text-anchor="middle" font-size="14" font-weight="bold">'
                f'{self._xml_escape(spec.title)}</text>'
            )
        y_label = y_enc.label or y_enc.field
        out.append(
            f'<text x="{10}" y="{_MARGIN_TOP + ch / 2}" '
            f'text-anchor="middle" '
            f'transform="rotate(-90, 10, {_MARGIN_TOP + ch / 2})" '
            f'font-size="11">{self._xml_escape(y_label)}</text>'
        )
        for t in _nice_ticks(y_min, y_max, 5):
            y = _y_pos(t, ch, y_min, y_max)
            out.append(
                f'<line x1="{_MARGIN_LEFT}" y1="{y:.1f}" '
                f'x2="{_MARGIN_LEFT + cw}" y2="{y:.1f}" '
                f'stroke="#eee" stroke-width="1"/>'
            )
            out.append(
                f'<text x="{_MARGIN_LEFT - 5}" y="{y:.1f}" '
                f'text-anchor="end" dominant-baseline="central" '
                f'font-size="10">{_format_number(t)}</text>'
            )
        for i, (cat, val) in enumerate(zip(cats, vals)):
            bx = _MARGIN_LEFT + i * band + (band - bar_w) / 2
            by = _y_pos(val, ch, y_min, y_max)
            bh = max(_bar_height(val, ch, y_min, y_max), 1)
            color = _COLORS[i % len(_COLORS)]
            out.append(
                f'<rect x="{bx:.1f}" y="{by:.1f}" '
                f'width="{bar_w:.1f}" height="{bh:.1f}" '
                f'fill="{color}" stroke="none"/>'
            )
            lx = _MARGIN_LEFT + i * band + band / 2
            out.append(
                f'<text x="{lx:.1f}" y="{h - _MARGIN_BOTTOM + 15}" '
                f'text-anchor="end" '
                f'transform="rotate(-45, {lx:.1f}, {h - _MARGIN_BOTTOM + 15})" '
                f'font-size="9">{self._xml_escape(cat)}</text>'
            )
        base_y = _y_pos(max(0, y_min), ch, y_min, y_max)
        out.append(
            f'<line x1="{_MARGIN_LEFT}" y1="{base_y:.1f}" '
            f'x2="{_MARGIN_LEFT + cw}" y2="{base_y:.1f}" '
            f'stroke="#333" stroke-width="1"/>'
        )
        out.append("</svg>")
        return "\n".join(out)

    def _render_line(
        self, spec: ViewSpec, rows: list[dict[str, Any]]
    ) -> str:
        x_enc = spec.encoding_for(EncodingChannel.X)
        y_enc = spec.encoding_for(EncodingChannel.Y)
        if not x_enc or not y_enc:
            return self._empty_chart(spec)
        cats = [str(row.get(x_enc.field, "")) for row in rows]
        vals = [_to_number(row.get(y_enc.field, 0)) for row in rows]
        n = len(cats)
        w = max(spec.width, 100)
        h = max(spec.height, 100)
        cw = w - _MARGIN_LEFT - _MARGIN_RIGHT
        ch = h - _MARGIN_TOP - _MARGIN_BOTTOM
        y_min, y_max = _compute_y_range(vals)
        out: list[str] = []
        self._svg_header(out, w, h)
        if spec.title:
            out.append(
                f'<text x="{w / 2}" y="{_MARGIN_TOP - 10}" '
                f'text-anchor="middle" font-size="14" font-weight="bold">'
                f'{self._xml_escape(spec.title)}</text>'
            )
        y_label = y_enc.label or y_enc.field
        out.append(
            f'<text x="{10}" y="{_MARGIN_TOP + ch / 2}" '
            f'text-anchor="middle" '
            f'transform="rotate(-90, 10, {_MARGIN_TOP + ch / 2})" '
            f'font-size="11">{self._xml_escape(y_label)}</text>'
        )
        for t in _nice_ticks(y_min, y_max, 5):
            y = _y_pos(t, ch, y_min, y_max)
            out.append(
                f'<line x1="{_MARGIN_LEFT}" y1="{y:.1f}" '
                f'x2="{_MARGIN_LEFT + cw}" y2="{y:.1f}" '
                f'stroke="#eee" stroke-width="1"/>'
            )
            out.append(
                f'<text x="{_MARGIN_LEFT - 5}" y="{y:.1f}" '
                f'text-anchor="end" dominant-baseline="central" '
                f'font-size="10">{_format_number(t)}</text>'
            )
        points: list[tuple[float, float]] = []
        for i in range(n):
            x = _MARGIN_LEFT + (i * cw / max(n - 1, 1))
            y = _y_pos(vals[i], ch, y_min, y_max)
            points.append((x, y))
        if points:
            color = _COLORS[0]
            pd = " ".join(f"{p[0]:.1f},{p[1]:.1f}" for p in points)
            out.append(
                f'<polyline fill="none" stroke="{color}" stroke-width="2" '
                f'points="{pd}"/>'
            )
            for px, py in points:
                out.append(
                    f'<circle cx="{px:.1f}" cy="{py:.1f}" '
                    f'r="4" fill="{color}"/>'
                )
            for i, (px, _) in enumerate(points):
                out.append(
                    f'<text x="{px:.1f}" y="{h - _MARGIN_BOTTOM + 15}" '
                    f'text-anchor="end" '
                    f'transform="rotate(-45, {px:.1f}, {h - _MARGIN_BOTTOM + 15})" '
                    f'font-size="9">{self._xml_escape(cats[i])}</text>'
                )
        out.append("</svg>")
    def _empty_chart(self, spec: ViewSpec) -> str:
            w = max(spec.width, 200)
            h = max(spec.height, 100)
            lines = [
                f'<svg xmlns="http://www.w3.org/2000/svg" '
                f'width="{w}" height="{h}" '
                f'viewBox="0 0 {w} {h}" '
                f'font-family="system-ui, -apple-system, sans-serif" '
                f'style="background: white">',
                f'<text x="{w / 2}" y="{h / 2}" '
                f'text-anchor="middle" dominant-baseline="central" '
                f'font-size="13" fill="#999">'
                f'No data to display</text>',
                "</svg>",
            ]
            return "\n".join(lines)

    @staticmethod
    def _svg_header(out: list[str], width: int, height: int) -> None:
        out.append(
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" '
            f'font-family="system-ui, -apple-system, sans-serif" '
            f'style="background: white">'
        )

    @staticmethod
    def _xml_escape(s: str) -> str:
        return (
            s.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )


# Pure helper functions


def _to_number(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("$", "").replace("€", ""))
    except (ValueError, TypeError):
        return 0.0


def _compute_y_range(values: list[float]) -> tuple[float, float]:
    if not values:
        return (0, 1)
    v_min = min(values)
    v_max = max(values)
    if v_min == v_max:
        if v_min == 0:
            return (0, 1)
        pad = abs(v_min) * 0.1
        return (max(0, v_min - pad), v_min + pad)
    pad = (v_max - v_min) * 0.05
    return (v_min - pad, v_max + pad)


def _nice_ticks(y_min: float, y_max: float, target_count: int = 5) -> list[float]:
    if y_min == y_max:
        return [y_min]
    span = y_max - y_min
    raw_step = span / max(target_count, 1)
    magnitude = 10 ** math.floor(math.log10(raw_step)) if raw_step > 0 else 1
    residual = raw_step / magnitude if magnitude > 0 else 1
    if residual <= 1.5:
        nice_step = 1 * magnitude
    elif residual <= 3.5:
        nice_step = 2 * magnitude
    elif residual <= 7.5:
        nice_step = 5 * magnitude
    else:
        nice_step = 10 * magnitude
    start = math.floor(y_min / nice_step) * nice_step if nice_step > 0 else 0
    ticks = []
    current = start
    while current <= y_max + nice_step:
        ticks.append(current)
        current += nice_step
    return ticks


def _y_pos(value: float, chart_h: float, y_min: float, y_max: float) -> float:
    if y_max == y_min:
        return _MARGIN_TOP
    return _MARGIN_TOP + chart_h - ((value - y_min) / (y_max - y_min) * chart_h)


def _bar_height(value: float, chart_h: float, y_min: float, y_max: float) -> float:
    y_val = _y_pos(value, chart_h, y_min, y_max)
    baseline = y_min if y_min < 0 else 0
    y_zero = _y_pos(baseline, chart_h, y_min, y_max)
    return abs(y_val - y_zero)


def _format_number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:.2f}"
        return "\n".join(out)