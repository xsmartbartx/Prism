"""SVG Renderer — renders ViewSpec + data into SVG output.

Phase 0 v0: Bar, line, and table charts with SVG output.
Rendering is deterministic: same spec + same data → identical SVG.
"""

from __future__ import annotations

import math
from typing import Any

from presentation.spec.view_spec import EncodingChannel, MarkType, ViewSpec

# Default color palette (Tableau 10)
_COLORS = [
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2",
    "#59a14f", "#edc948", "#b07aa1", "#ff9da7",
]

# Layout constants
_MARGIN_TOP = 30
_MARGIN_RIGHT = 20
_MARGIN_BOTTOM = 60
_MARGIN_LEFT = 60


class SvgRenderer:
    """Renders a ViewSpec + data rows into an SVG string.

    The renderer is a pure function with no side effects.
    It receives results; it never fetches them.
    """

    def render(self, spec: ViewSpec, rows: list[dict[str, Any]]) -> str:
        """Render a chart to SVG.

        Args:
            spec: The validated ViewSpec.
            rows: Data rows (list of dicts) from the query result.

        Returns:
            An SVG string.
        """
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