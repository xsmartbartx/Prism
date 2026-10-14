"""SVG Renderer - renders ViewSpec + data into SVG output.

Phase 0 v0: Bar, line, and table charts with SVG output.
"""

from __future__ import annotations
import math
from typing import Any
from presentation.spec.view_spec import EncodingChannel, MarkType, ViewSpec

_COLORS = [
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2",
    "#59a14f", "#edc948", "#b07aa1", "#ff9da7",
]
_MT = 30
_MR = 20
_MB = 60
_ML = 60


class SvgRenderer:
    """Renders a ViewSpec + data rows into an SVG string."""

    def render(self, spec: ViewSpec, rows: list[dict[str, Any]]) -> str:
        """Render a chart to SVG."""
        if not rows:
            return self._empty(spec)
        m = spec.mark
        if m == MarkType.TABLE:
            return self._table(spec, rows)
        elif m == MarkType.BAR:
            return self._bar(spec, rows)
        elif m == MarkType.LINE:
            return self._line(spec, rows)
        return self._empty(spec)

    def _empty(self, spec: ViewSpec) -> str:
        """Render empty chart placeholder."""
        w = max(spec.width, 200)
def _table(self, spec: ViewSpec, rows: list[dict[str, Any]]) -> str:
        """Render a data table as SVG."""
        xe = spec.encoding_for(EncodingChannel.X)
        ye = spec.encoding_for(EncodingChannel.Y)
        if xe and ye:
            cols = [xe.field, ye.field]
        else:
            cols = list(rows[0].keys())[:5] if rows else []
        cw = min(120, max(60, (spec.width - 120) // max(len(cols), 1)))
        rh, hh = 22, 26
        tw = len(cols) * cw
        w = max(spec.width, tw + 20)
        h = max(spec.height, 20 + hh + len(rows) * rh + 10)
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}"'
            f' font-family="system-ui, sans-serif">'
            f'<rect x="10" y="10" width="{tw}" height="{hh}"'
            f' fill="#e8e8e8" stroke="#ccc"/>'
        )
        for ci, col in enumerate(cols):
            x = 10 + ci * cw
            svg += (
                f'<rect x="{x}" y="10" width="{cw}" height="{hh}"'
                f' fill="none" stroke="#ccc"/>'
                f'<text x="{x + cw/2}" y="{10 + hh/2}"'
                f' text-anchor="middle" dominant-baseline="central"'
                f' font-size="12" font-weight="bold">{col}</text>'
            )
        for ri, row in enumerate(rows):
            y = 10 + hh + ri * rh
            bg = "#f8f8f8" if ri % 2 else "#ffffff"
            svg += (
                f'<rect x="10" y="{y}" width="{tw}" height="{rh}"'
                f' fill="{bg}" stroke="#ccc"/>'
            )
            for ci, col in enumerate(cols):
                vx = 10 + ci * cw
                val = str(row.get(col, ""))
                svg += (
                    f'<rect x="{vx}" y="{y}" width="{cw}" height="{rh}"'
                    f' fill="none" stroke="#ccc"/>'
                    f'<text x="{vx + 4}" y="{y + rh/2}"'
                    f' dominant-baseline="central" font-size="11">'
                    f'{self._xml(val)}</text>'
                )
        svg += "</svg>"
def _bar(self, spec: ViewSpec, rows: list[dict[str, Any]]) -> str:
        """Render a vertical bar chart as SVG."""
        xe = spec.encoding_for(EncodingChannel.X)
        ye = spec.encoding_for(EncodingChannel.Y)
        if not xe or not ye:
            return self._empty(spec)
        cats = [str(row.get(xe.field, "")) for row in rows]
        vals = [_to_num(row.get(ye.field, 0)) for row in rows]
        n = len(cats)
        w = max(spec.width, 200)
        h = max(spec.height, 200)
        cw = w - _ML - _MR
        ch = h - _MT - _MB
        ymin, ymax = _yrange(vals)
        band = cw / max(n, 1)
        bw = band * 0.7
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}"'
            f' viewBox="0 0 {w} {h}"'
            f' font-family="system-ui, sans-serif" style="background:white">'
        )
        for t in _ticks(ymin, ymax, 5):
            y = _ypos(t, ch, ymin, ymax)
            svg += (
                f'<line x1="{_ML}" y1="{y:.1f}"'
                f' x2="{_ML + cw}" y2="{y:.1f}"'
                f' stroke="#eee" stroke-width="1"/>'
            )
        for i in range(n):
            bx = _ML + i * band + (band - bw) / 2
            by = _ypos(vals[i], ch, ymin, ymax)
            bh = max(_bheight(vals[i], ch, ymin, ymax), 1)
            c = _COLORS[i % len(_COLORS)]
            svg += (
                f'<rect x="{bx:.1f}" y="{by:.1f}"'
                f' width="{bw:.1f}" height="{bh:.1f}"'
                f' fill="{c}" stroke="none"/>'
            )
            lx = _ML + i * band + band / 2
            svg += (
                f'<text x="{lx:.1f}" y="{h - _MB + 15}"'
                f' text-anchor="end" font-size="9">'
                f'{self._xml(cats[i])}</text>'
            )
        svg += "</svg>"
        return svg
        return svg
        h = max(spec.height, 100)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}"'
            f' viewBox="0 0 {w} {h}"'
            f' font-family="system-ui, sans-serif" style="background:white">'
            f'<text x="{w/2}" y="{h/2}" text-anchor="middle"'
            f' dominant-baseline="central" font-size="13" fill="#999">'
            f'No data to display</text></svg>'
        )