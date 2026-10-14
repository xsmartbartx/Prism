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

    def _empty(self, spec: ViewSpec) -> str: return '<svg><text>No data</text></svg>'
    def _table(self, spec: ViewSpec, rows: list[dict[str, Any]]) -> str: return '<svg><text>Table</text></svg>'
    def _bar(self, spec: ViewSpec, rows: list[dict[str, Any]]) -> str: return '<svg><text>Bar</text></svg>'
    def _line(self, spec: ViewSpec, rows: list[dict[str, Any]]) -> str: return '<svg><text>Line</text></svg>'
    @staticmethod
    def render_xml(s: str) -> str: return s.replace("&", "&amp;").replace("<", "&lt;")