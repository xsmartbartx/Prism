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
        return s