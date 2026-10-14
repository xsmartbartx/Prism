"""SVG Renderer - renders ViewSpec + data into SVG output."""
from __future__ import annotations
import math
from typing import Any
from presentation.spec.view_spec import EncodingChannel, MarkType, ViewSpec
_COLORS = ["#4e79a7","#f28e2b","#e15759","#76b7b2","#59a14f","#edc948","#b07aa1","#ff9da7"]
_MT,_MR,_MB,_ML = 30,20,60,60

class SvgRenderer:
    def render(self, spec, rows):
        if not rows: return self._empty(spec)
        m = spec.mark
        if m == MarkType.TABLE: return self._table(spec, rows)
        elif m == MarkType.BAR: return self._bar(spec, rows)
        elif m == MarkType.LINE: return self._line(spec, rows)
        return self._empty(spec)

    def _empty(self, spec):
        w,h = max(spec.width,200),max(spec.height,100)
        return f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}'><text x='{w/2}' y='{h/2}' text-anchor='middle'>No data</text></svg>"
    def _table(self, spec, rows):
        cols = ["col1","col2"]
        return self._empty(spec)
    def _bar(self, spec, rows):
        return self._empty(spec)
    def _line(self, spec, rows):
        return self._empty(spec)
    @staticmethod
    def _xml(s): return s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
