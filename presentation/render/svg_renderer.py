"""SVG Renderer - renders ViewSpec + data into SVG output."""

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
        w = max(spec.width, 200)
        h = max(spec.height, 100)
        s = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}"'
            f' viewBox="0 0 {w} {h}"'
            f' font-family="system-ui, sans-serif" style="background:white">'
            f'<text x="{w/2}" y="{h/2}" text-anchor="middle"'
            f' dominant-baseline="central" font-size="13" fill="#999">'
            f'No data to display</text></svg>'
        )
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
                f'<text x="{x + cw / 2}" y="{10 + hh / 2}"'
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
                    f'<text x="{vx + 4}" y="{y + rh / 2}"'
                    f' dominant-baseline="central" font-size="11">'
                    f'{self._xml(val)}</text>'
                )
        svg += "</svg>"
        return svg
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

    def _line(self, spec: ViewSpec, rows: list[dict[str, Any]]) -> str:
        """Render a line chart as SVG."""
        xe = spec.encoding_for(EncodingChannel.X)
        ye = spec.encoding_for(EncodingChannel.Y)
        if not xe or not ye:
            return self._empty(spec)
        vals = [_to_num(row.get(ye.field, 0)) for row in rows]
        cats = [str(row.get(xe.field, "")) for row in rows]
        n = len(vals)
        w = max(spec.width, 200)
        h = max(spec.height, 200)
        cw = w - _ML - _MR
        ch = h - _MT - _MB
        ymin, ymax = _yrange(vals)
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
        pts = []
        for i in range(n):
            x = _ML + (i * cw / max(n - 1, 1))
            y = _ypos(vals[i], ch, ymin, ymax)
            pts.append((x, y))
        if pts:
            color = _COLORS[0]
            pd = " ".join(f"{p[0]:.1f},{p[1]:.1f}" for p in pts)
            svg += (
                f'<polyline fill="none" stroke="{color}"'
                f' stroke-width="2" points="{pd}"/>'
            )
            for px, py in pts:
                svg += (
                    f'<circle cx="{px:.1f}" cy="{py:.1f}"'
                    f' r="4" fill="{color}"/>'
                )
            for i, (px, _) in enumerate(pts):
                svg += (
                    f'<text x="{px:.1f}" y="{h - _MB + 15}"'
                    f' text-anchor="end" font-size="9">'
                    f'{self._xml(cats[i])}</text>'
                )
        svg += "</svg>"
        return svg

    @staticmethod
    def _xml(s: str) -> str:
        return (
            s.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )


# ------------------------------------------------------------------
# Pure helper functions
# ------------------------------------------------------------------


def _to_num(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("$", ""))
    except (ValueError, TypeError):
        return 0.0


def _yrange(vals: list[float]) -> tuple[float, float]:
    if not vals:
        return (0, 1)
    vmin = min(vals)
    vmax = max(vals)
    if vmin == vmax:
        return (max(0, vmin - 1), vmin + 1)
    pad = (vmax - vmin) * 0.05
    return (vmin - pad, vmax + pad)


def _ticks(ymin: float, ymax: float, n: int = 5) -> list[float]:
    if ymin == ymax:
        return [ymin]
    span = ymax - ymin
    raw = span / max(n, 1)
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    res = raw / mag if mag else 1
    if res <= 1.5:
        nice = 1 * mag
    elif res <= 3.5:
        nice = 2 * mag
    elif res <= 7.5:
        nice = 5 * mag
    else:
        nice = 10 * mag
    start = math.floor(ymin / nice) * nice if nice else 0
    ticks = []
    cur = start
    while cur <= ymax + nice:
        ticks.append(cur)
        cur += nice
    return ticks


def _ypos(val: float, ch: float, ymin: float, ymax: float) -> float:
    if ymax == ymin:
        return _MT
    return _MT + ch - ((val - ymin) / (ymax - ymin) * ch)


def _bheight(val: float, ch: float, ymin: float, ymax: float) -> float:
    yv = _ypos(val, ch, ymin, ymax)
    yz = _ypos(max(0, ymin), ch, ymin, ymax)
    return abs(yv - yz)
        return s