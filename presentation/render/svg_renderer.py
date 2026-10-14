"""SVG Renderer."""
from __future__ import annotations
import math
from typing import Any
from presentation.spec.view_spec import EncodingChannel, MarkType, ViewSpec

class SvgRenderer:
    def render(self, spec: ViewSpec, rows: list[dict[str, Any]]) -> str:
        if not rows: return self._empty(spec)
        m = spec.mark
        if m == MarkType.TABLE: return self._table(spec, rows)
        elif m == MarkType.BAR: return self._bar(spec, rows)
        elif m == MarkType.LINE: return self._line(spec, rows)
        return self._empty(spec)

    def _empty(self, spec: ViewSpec) -> str:
        w = max(spec.width, 200)
        h = max(spec.height, 100)
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}"'
                f' viewBox="0 0 {w} {h}" font-family="system-ui, sans-serif">'
                f'<text x="{w/2}" y="{h/2}" text-anchor="middle"'
                f' dominant-baseline="central" font-size="13" fill="#999">'
                f'No data</text></svg>')

    def _table(self, spec: ViewSpec, rows: list[dict[str, Any]]) -> str:
        xe = spec.encoding_for(EncodingChannel.X)
        ye = spec.encoding_for(EncodingChannel.Y)
        cols = [xe.field, ye.field] if xe and ye else (list(rows[0].keys())[:5] if rows else [])
        cw = min(120, max(60, (spec.width - 120) // max(len(cols), 1)))
        rh, hh = 22, 26
        tw = len(cols) * cw
        w = max(spec.width, tw + 20)
        h = max(spec.height, 20 + hh + len(rows) * rh + 10)
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}"'
               f' font-family="system-ui, sans-serif">'
               f'<rect x="10" y="10" width="{tw}" height="{hh}"'
               f' fill="#e8e8e8" stroke="#ccc"/>')
        for ci, col in enumerate(cols):
            x = 10 + ci * cw
            svg += (f'<rect x="{x}" y="10" width="{cw}" height="{hh}"'
                    f'fill="none" stroke="#ccc"/>'
                    f'<text x="{x + cw/2}" y="{10 + hh/2}" text-anchor="middle"'
                    f' dominant-baseline="central" font-size="12" font-weight="bold">'
                    f'{col}</text>')
        for ri, row in enumerate(rows):
            y = 10 + hh + ri * rh
            bg = "#f8f8f8" if ri % 2 else "#ffffff"
            svg += f'<rect x="10" y="{y}" width="{tw}" height="{rh}" fill="{bg}" stroke="#ccc"/>'
            for ci, col in enumerate(cols):
                vx = 10 + ci * cw
                val = str(row.get(col, ""))
                svg += (f'<rect x="{vx}" y="{y}" width="{cw}" height="{rh}"'
                        f' fill="none" stroke="#ccc"/>'
                        f'<text x="{vx + 4}" y="{y + rh/2}"'
                        f' dominant-baseline="central" font-size="11">'
                        f'{self._xml(val)}</text>')
        svg += "</svg>"
        return svg
    def _bar(self, spec: ViewSpec, rows: list[dict[str, Any]]) -> str:
        xe = spec.encoding_for(EncodingChannel.X)
        ye = spec.encoding_for(EncodingChannel.Y)
        if not xe or not ye: return self._empty(spec)
        cats = [str(row.get(xe.field, "")) for row in rows]
        vals = [_to_num(row.get(ye.field, 0)) for row in rows]
        n = len(cats)
        w = max(spec.width, 200)
        h = max(spec.height, 200)
        cw = w - 80
        ch = h - 90
        ymin, ymax = _yrange(vals)
        band = cw / max(n, 1)
        bw = band * 0.7
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}"'
               f' viewBox="0 0 {w} {h}" font-family="system-ui, sans-serif">')
        for t in _ticks(ymin, ymax, 5):
            y = _ypos(t, ch, ymin, ymax)
            svg += (f'<line x1="60" y1="{y:.1f}" x2="{60 + cw}" y2="{y:.1f}"'
                    f' stroke="#eee" stroke-width="1"/>')
        for i in range(n):
            bx = 60 + i * band + (band - bw) / 2
            by = _ypos(vals[i], ch, ymin, ymax)
            bh = max(_bheight(vals[i], ch, ymin, ymax), 1)
            color = _COLORS[i % 8]
            svg += (f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}"'
                    f' height="{bh:.1f}" fill="{color}" stroke="none"/>')
            lx = 60 + i * band + band / 2
            svg += (f'<text x="{lx:.1f}" y="{h - 15}"'
                    f' text-anchor="end" font-size="9">'
                    f'{self._xml(cats[i])}</text>')
        svg += "</svg>"
        return svg

    def _line(self, spec: ViewSpec, rows: list[dict[str, Any]]) -> str:
        xe = spec.encoding_for(EncodingChannel.X)
        ye = spec.encoding_for(EncodingChannel.Y)
        if not xe or not ye: return self._empty(spec)
        vals = [_to_num(row.get(ye.field, 0)) for row in rows]
        cats = [str(row.get(xe.field, "")) for row in rows]
        n = len(vals)
        w = max(spec.width, 200)
        h = max(spec.height, 200)
        cw = w - 80
        ch = h - 90
        ymin, ymax = _yrange(vals)
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}"'
               f' viewBox="0 0 {w} {h}" font-family="system-ui, sans-serif">')
        for t in _ticks(ymin, ymax, 5):
            y = _ypos(t, ch, ymin, ymax)
            svg += (f'<line x1="60" y1="{y:.1f}" x2="{60 + cw}" y2="{y:.1f}"'
                    f' stroke="#eee" stroke-width="1"/>')
        pts = []
        for i in range(n):
            x = 60 + (i * cw / max(n - 1, 1))
            y = _ypos(vals[i], ch, ymin, ymax)
            pts.append((x, y))
        if pts:
            color = _COLORS[0]
            pd = " ".join(f"{p[0]:.1f},{p[1]:.1f}" for p in pts)
            svg += (f'<polyline fill="none" stroke="{color}" stroke-width="2"'
                    f' points="{pd}"/>')
            for px, py in pts:
                svg += f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="{color}"/>'
        svg += "</svg>"
        return svg
    def _line(self, spec: ViewSpec, rows: list[dict[str, Any]]) -> str: return '<svg><text>Line</text></svg>'
    @staticmethod
    def _xml(self, s: str) -> str:
        return (s.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;")
                .replace("'", "&apos;"))