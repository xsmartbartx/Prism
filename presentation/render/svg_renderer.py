"""SVG renderer — the one renderer for screen, export and share.

Deterministic: the same (view spec, rows) always yields byte-identical
SVG, so charts can be golden-tested and cached by content hash.

Accessible by construction (architecture §9.7): every chart is
``role="img"`` with a ``<title>`` and ``<desc>``; every mark carries a
``<title>`` tooltip with its exact value; bars start at zero; series
colours come from a colour-blind-safe palette and are never the only
carrier of meaning (legends and labels always name the series).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from presentation.render.format import format_category, format_number
from presentation.spec.view_spec import (
    EncodingChannel,
    MarkType,
    Orientation,
    ViewSpec,
)

# Okabe–Ito inspired, colour-blind-safe categorical palette.
_COLORS = [
    "#4e79a7",
    "#f28e2b",
    "#59a14f",
    "#e15759",
    "#76b7b2",
    "#edc948",
    "#b07aa1",
    "#ff9da7",
    "#9c755f",
    "#bab0ac",
]

_THEMES = {
    "light": {
        "bg": "#ffffff",
        "text": "#1f2328",
        "muted": "#59636e",
        "grid": "#eeeeee",
        "axis": "#d0d7de",
        "stripe": "#f6f8fa",
    },
    "dark": {
        "bg": "#0d1117",
        "text": "#e6edf3",
        "muted": "#9198a1",
        "grid": "#21262d",
        "axis": "#3d444d",
        "stripe": "#161b22",
    },
}

_FONT = "system-ui, -apple-system, Segoe UI, Roboto, sans-serif"


def _xml(s: object) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _f(v: float) -> str:
    """Compact, deterministic coordinate formatting."""
    r = round(v, 1)
    return str(int(r)) if r == int(r) else f"{r:.1f}"


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max(max_chars - 1, 1)] + "…"


@dataclass
class _Series:
    name: str
    values: list[float | None]
    color: str


class SvgRenderer:
    """Render a ViewSpec + result rows into a standalone SVG document."""

    def render(self, spec: ViewSpec, rows: list[dict[str, Any]]) -> str:
        theme = _THEMES.get(spec.theme, _THEMES["light"])
        if not rows:
            return self._empty(spec, theme)
        m = spec.mark
        if m == MarkType.TABLE:
            return self._table(spec, rows, theme)
        if m == MarkType.KPI:
            return self._kpi(spec, rows, theme)
        if m == MarkType.PIE:
            return self._pie(spec, rows, theme)
        if m == MarkType.SCATTER:
            return self._scatter(spec, rows, theme)
        if m in (MarkType.BAR, MarkType.LINE, MarkType.AREA):
            return self._cartesian(spec, rows, theme)
        return self._empty(spec, theme)  # pragma: no cover

    # ------------------------------------------------------------------
    # Frame
    # ------------------------------------------------------------------

    def _open(self, spec: ViewSpec, w: float, h: float, theme: dict[str, str]) -> str:
        title = spec.title or "Chart"
        desc = spec.description or self._auto_desc(spec)
        out = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{_f(w)}" height="{_f(h)}"'
            f' viewBox="0 0 {_f(w)} {_f(h)}" font-family="{_FONT}" role="img"'
            f' aria-labelledby="t d">'
            f'<title id="t">{_xml(title)}</title><desc id="d">{_xml(desc)}</desc>'
            f'<rect width="100%" height="100%" fill="{theme["bg"]}"/>'
        )
        if spec.title:
            out += (
                f'<text x="16" y="24" font-size="15" font-weight="600"'
                f' fill="{theme["text"]}">{_xml(_truncate(spec.title, 90))}</text>'
            )
        return out

    @staticmethod
    def _auto_desc(spec: ViewSpec) -> str:
        x = spec.encoding_for(EncodingChannel.X)
        ys = spec.encodings_for(EncodingChannel.Y)
        parts = [f"{spec.mark.value} chart"]
        if ys:
            parts.append("of " + ", ".join(e.label or e.field for e in ys))
        if x:
            parts.append(f"by {x.label or x.field}")
        return " ".join(parts)

    def _empty(self, spec: ViewSpec, theme: dict[str, str] | None = None) -> str:
        theme = theme or _THEMES["light"]
        w = max(spec.width, 200)
        h = max(spec.height, 100)
        return (
            self._open(spec, w, h, theme)
            + f'<text x="{_f(w / 2)}" y="{_f(h / 2)}" text-anchor="middle"'
            f' dominant-baseline="central" font-size="13" fill="{theme["muted"]}">'
            "No data</text></svg>"
        )

    def _fmt(self, spec: ViewSpec, v: Any, *, axis: bool = False) -> str:
        return format_number(
            v, spec.number_format, locale=spec.locale, currency=spec.currency, compact_axis=axis
        )

    def _cat(self, spec: ViewSpec, v: Any) -> str:
        if isinstance(v, int) and not isinstance(v, bool):
            return str(v)  # years, codes: never thousands-grouped
        return format_category(v, locale=spec.locale, time_grain=spec.time_grain)

    # ------------------------------------------------------------------
    # Series extraction
    # ------------------------------------------------------------------

    def _series(
        self, spec: ViewSpec, rows: list[dict[str, Any]]
    ) -> tuple[list[Any], list[_Series]]:
        xe = spec.encoding_for(EncodingChannel.X)
        ys = spec.encodings_for(EncodingChannel.Y)
        ce = spec.encoding_for(EncodingChannel.COLOR)
        if not xe or not ys:
            return [], []
        cats: list[Any] = []
        seen: set[Any] = set()
        for r in rows:
            k = r.get(xe.field)
            if k not in seen:
                seen.add(k)
                cats.append(k)
        cats = cats[: spec.max_categories]
        index = {c: i for i, c in enumerate(cats)}
        series: list[_Series] = []
        if ce and ce.field != xe.field:
            names: list[Any] = []
            for r in rows:
                n = r.get(ce.field)
                if n not in names:
                    names.append(n)
            names = names[:10]
            for si, n in enumerate(names):
                vals: list[float | None] = [None] * len(cats)
                for r in rows:
                    if r.get(ce.field) == n and r.get(xe.field) in index:
                        vals[index[r.get(xe.field)]] = _num_or_none(r.get(ys[0].field))
                series.append(_Series(self._cat(spec, n), vals, _COLORS[si % len(_COLORS)]))
        else:
            for si, ye in enumerate(ys[:10]):
                vals = [None] * len(cats)
                for r in rows:
                    if r.get(xe.field) in index:
                        vals[index[r.get(xe.field)]] = _num_or_none(r.get(ye.field))
                series.append(_Series(ye.label or ye.field, vals, _COLORS[si % len(_COLORS)]))
        return cats, series

    # ------------------------------------------------------------------
    # Bar / line / area
    # ------------------------------------------------------------------

    def _legend(
        self, series: list[_Series], x: float, y: float, w: float, theme: dict[str, str]
    ) -> tuple[str, float]:
        out, cx, cy = "", x, y
        for s in series:
            label = _truncate(s.name, 28)
            item_w = 18 + len(label) * 6.5 + 14
            if cx + item_w > x + w and cx > x:
                cx, cy = x, cy + 18
            out += (
                f'<rect x="{_f(cx)}" y="{_f(cy - 9)}" width="10" height="10" rx="2"'
                f' fill="{s.color}"/><text x="{_f(cx + 14)}" y="{_f(cy)}" font-size="11"'
                f' fill="{theme["muted"]}">{_xml(label)}</text>'
            )
            cx += item_w
        return out, cy - y + 18

    def _cartesian(self, spec: ViewSpec, rows: list[dict[str, Any]], theme: dict[str, str]) -> str:
        cats, series = self._series(spec, rows)
        if not cats or not series:
            return self._empty(spec, theme)
        w, h = float(max(spec.width, 200)), float(max(spec.height, 160))
        horizontal = spec.mark == MarkType.BAR and spec.orientation == Orientation.HORIZONTAL
        stacked = spec.stacked and len(series) > 1
        xe = spec.encoding_for(EncodingChannel.X)
        ys = spec.encodings_for(EncodingChannel.Y)
        top = 40.0 if spec.title else 16.0
        legend_svg, legend_h = "", 0.0
        if spec.show_legend and len(series) > 1:
            legend_svg, legend_h = self._legend(series, 16, top + 4, w - 32, theme)
            top += legend_h + 4

        # Value domain (bars include zero; lines pad).
        if stacked:
            pos = [sum(max(s.values[i] or 0, 0) for s in series) for i in range(len(cats))]
            neg = [sum(min(s.values[i] or 0, 0) for s in series) for i in range(len(cats))]
            vmin, vmax = min([0.0, *neg]), max([0.0, *pos])
        else:
            allv = [v for s in series for v in s.values if v is not None]
            if not allv:
                return self._empty(spec, theme)
            if spec.mark == MarkType.LINE:
                vmin, vmax = _yrange(allv)
            else:
                vmin, vmax = min(0.0, min(allv)), max(0.0, max(allv))
        sc = spec.scales.get(EncodingChannel.Y)
        if sc and sc.domain_min is not None:
            vmin = sc.domain_min
        if sc and sc.domain_max is not None:
            vmax = sc.domain_max
        if vmin == vmax:
            vmax = vmin + 1
        ticks = _ticks(vmin, vmax, 5)
        vmin, vmax = min(vmin, ticks[0]), max(vmax, ticks[-1])

        cat_labels = [self._cat(spec, c) for c in cats]
        tick_labels = [self._fmt(spec, t, axis=True) for t in ticks]
        if horizontal:
            label_w = min(max(len(lb) for lb in cat_labels) * 6.4 + 8, w * 0.35)
            left, right, bottom = 16 + label_w, 16.0, 34.0
        else:
            left = 16 + max(len(t) for t in tick_labels) * 6.6 + 6
            right = 16.0
            longest = max(len(lb) for lb in cat_labels)
            band_guess = (w - left - right) / len(cats)
            rotate = longest * 6.2 > band_guess
            bottom = 30.0 + (min(longest, 18) * 4.6 if rotate else 0.0)
        y_title = (ys[0].label or ys[0].field) if len(ys) == 1 else ""
        if y_title and not horizontal:
            left += 16
        pw, ph = w - left - right, h - top - bottom
        if pw < 40 or ph < 40:
            return self._empty(spec, theme)

        def vpos(v: float) -> float:
            frac = (v - vmin) / (vmax - vmin)
            return left + frac * pw if horizontal else top + ph - frac * ph

        out = self._open(spec, w, h, theme) + legend_svg
        # Grid + value axis labels
        for t, lbl in zip(ticks, tick_labels, strict=True):
            if t < vmin - 1e-9 or t > vmax + 1e-9:
                continue
            p = vpos(t)
            if horizontal:
                out += (
                    f'<line x1="{_f(p)}" y1="{_f(top)}" x2="{_f(p)}" y2="{_f(top + ph)}"'
                    f' stroke="{theme["grid"]}" stroke-width="1"/>'
                    f'<text x="{_f(p)}" y="{_f(top + ph + 16)}" text-anchor="middle"'
                    f' font-size="10" fill="{theme["muted"]}">{_xml(lbl)}</text>'
                )
            else:
                out += (
                    f'<line x1="{_f(left)}" y1="{_f(p)}" x2="{_f(left + pw)}" y2="{_f(p)}"'
                    f' stroke="{theme["grid"]}" stroke-width="1"/>'
                    f'<text x="{_f(left - 6)}" y="{_f(p)}" text-anchor="end"'
                    f' dominant-baseline="central" font-size="10" fill="{theme["muted"]}">'
                    f"{_xml(lbl)}</text>"
                )
        zero = vpos(0.0) if vmin <= 0 <= vmax else vpos(vmin)
        if horizontal:
            out += (
                f'<line x1="{_f(zero)}" y1="{_f(top)}" x2="{_f(zero)}" y2="{_f(top + ph)}"'
                f' stroke="{theme["axis"]}"/>'
            )
        else:
            out += (
                f'<line x1="{_f(left)}" y1="{_f(zero)}" x2="{_f(left + pw)}" y2="{_f(zero)}"'
                f' stroke="{theme["axis"]}"/>'
            )
        if y_title and not horizontal:
            cy = top + ph / 2
            out += (
                f'<text x="14" y="{_f(cy)}" transform="rotate(-90 14 {_f(cy)})"'
                f' text-anchor="middle" font-size="11" fill="{theme["muted"]}">'
                f"{_xml(_truncate(y_title, 40))}</text>"
            )

        n = len(cats)
        band = (ph if horizontal else pw) / n
        # Category axis labels
        step = 1
        if not horizontal:
            step = max(1, math.ceil(n / max(pw / 28, 1)))
        for i, lbl in enumerate(cat_labels):
            if i % step:
                continue
            c = (top if horizontal else left) + band * (i + 0.5)
            if horizontal:
                out += (
                    f'<text x="{_f(left - 6)}" y="{_f(c)}" text-anchor="end"'
                    f' dominant-baseline="central" font-size="11" fill="{theme["text"]}">'
                    f"{_xml(_truncate(lbl, int((left - 22) / 6.4)))}</text>"
                )
            elif bottom > 31:
                yy = top + ph + 12
                out += (
                    f'<text x="{_f(c)}" y="{_f(yy)}" text-anchor="end" font-size="10"'
                    f' transform="rotate(-40 {_f(c)} {_f(yy)})" fill="{theme["text"]}">'
                    f"{_xml(_truncate(lbl, 18))}</text>"
                )
            else:
                out += (
                    f'<text x="{_f(c)}" y="{_f(top + ph + 16)}" text-anchor="middle"'
                    f' font-size="10" fill="{theme["text"]}">{_xml(lbl)}</text>'
                )
        if xe and not horizontal and (xe.label or len(series) == 1):
            pass  # category axis title is implied by labels; keep plots uncluttered

        if spec.mark == MarkType.BAR:
            out += self._bars(
                spec, cats, cat_labels, series, band, horizontal, stacked, vpos, top, left, theme
            )
        else:
            out += self._lines(
                spec, cats, cat_labels, series, band, vpos, top, left, zero, stacked, theme
            )
        return out + "</svg>"

    def _bars(
        self,
        spec: ViewSpec,
        cats: list[Any],
        labels: list[str],
        series: list[_Series],
        band: float,
        horizontal: bool,
        stacked: bool,
        vpos: Any,
        top: float,
        left: float,
        theme: dict[str, str],
    ) -> str:
        out = ""
        groups = 1 if stacked else len(series)
        inner = band * 0.72
        bw = inner / groups
        for i in range(len(cats)):
            start = (top if horizontal else left) + band * i + (band - inner) / 2
            pos_acc, neg_acc = 0.0, 0.0
            for si, s in enumerate(series):
                v = s.values[i]
                if v is None:
                    continue
                if stacked:
                    base = pos_acc if v >= 0 else neg_acc
                    a, b = vpos(base), vpos(base + v)
                    if v >= 0:
                        pos_acc += v
                    else:
                        neg_acc += v
                    off = start
                else:
                    a, b = vpos(0.0), vpos(v)
                    off = start + bw * si
                lo, hi = min(a, b), max(a, b)
                size = max(hi - lo, 0.5)
                tip = f"{labels[i]} · {s.name}: {self._fmt(spec, v)}"
                if horizontal:
                    out += (
                        f'<rect x="{_f(lo)}" y="{_f(off)}" width="{_f(size)}"'
                        f' height="{_f(max(bw - 1, 1))}" fill="{s.color}">'
                        f"<title>{_xml(tip)}</title></rect>"
                    )
                    if spec.show_values and not stacked:
                        out += (
                            f'<text x="{_f(hi + 4)}" y="{_f(off + bw / 2)}"'
                            f' dominant-baseline="central" font-size="10"'
                            f' fill="{theme["muted"]}">{_xml(self._fmt(spec, v))}</text>'
                        )
                else:
                    out += (
                        f'<rect x="{_f(off)}" y="{_f(lo)}" width="{_f(max(bw - 1, 1))}"'
                        f' height="{_f(size)}" fill="{s.color}">'
                        f"<title>{_xml(tip)}</title></rect>"
                    )
                    if spec.show_values and not stacked:
                        out += (
                            f'<text x="{_f(off + bw / 2)}" y="{_f(lo - 4)}"'
                            f' text-anchor="middle" font-size="10"'
                            f' fill="{theme["muted"]}">{_xml(self._fmt(spec, v))}</text>'
                        )
        return out

    def _lines(
        self,
        spec: ViewSpec,
        cats: list[Any],
        labels: list[str],
        series: list[_Series],
        band: float,
        vpos: Any,
        top: float,
        left: float,
        zero: float,
        stacked: bool,
        theme: dict[str, str],
    ) -> str:
        out = ""
        acc = [0.0] * len(cats)
        area = spec.mark == MarkType.AREA
        for s in series:
            pts: list[tuple[float, float, float, float | None]] = []
            for i, v in enumerate(s.values):
                x = left + band * (i + 0.5)
                if v is None:
                    pts.append((x, math.nan, math.nan, None))
                    continue
                base = acc[i] if (stacked and area) else 0.0
                y = vpos(base + v)
                y0 = vpos(base) if (stacked and area) else zero
                if stacked and area:
                    acc[i] += v
                pts.append((x, y, y0, v))
            segments: list[list[tuple[float, float, float, float | None]]] = [[]]
            for p in pts:
                if p[3] is None:
                    if segments[-1]:
                        segments.append([])
                else:
                    segments[-1].append(p)
            for seg in segments:
                if not seg:
                    continue
                line = " ".join(f"{_f(x)},{_f(y)}" for x, y, _, _ in seg)
                if area:
                    poly = line + " " + " ".join(f"{_f(x)},{_f(y0)}" for x, _, y0, _ in seg[::-1])
                    out += f'<polygon points="{poly}" fill="{s.color}" fill-opacity="0.25"/>'
                out += (
                    f'<polyline fill="none" stroke="{s.color}" stroke-width="2"'
                    f' stroke-linejoin="round" stroke-linecap="round" points="{line}"/>'
                )
            dense = len(cats) > 60
            for i, (x, y, _, v) in enumerate(pts):
                if v is None:
                    continue
                tip = f"{labels[i]} · {s.name}: {self._fmt(spec, v)}"
                r = 2 if dense else 3.5
                out += (
                    f'<circle cx="{_f(x)}" cy="{_f(y)}" r="{r}" fill="{s.color}"'
                    f' stroke="{theme["bg"]}" stroke-width="1"><title>{_xml(tip)}</title></circle>'
                )
                if spec.show_values and not dense:
                    out += (
                        f'<text x="{_f(x)}" y="{_f(y - 8)}" text-anchor="middle" font-size="10"'
                        f' fill="{theme["muted"]}">{_xml(self._fmt(spec, v))}</text>'
                    )
        return out

    # ------------------------------------------------------------------
    # Scatter
    # ------------------------------------------------------------------

    def _scatter(self, spec: ViewSpec, rows: list[dict[str, Any]], theme: dict[str, str]) -> str:
        xe = spec.encoding_for(EncodingChannel.X)
        ye = spec.encoding_for(EncodingChannel.Y)
        ce = spec.encoding_for(EncodingChannel.COLOR)
        if not xe or not ye:
            return self._empty(spec, theme)
        pts: list[tuple[float, float, Any]] = []
        for r in rows:
            xv, yv = _num_or_none(r.get(xe.field)), _num_or_none(r.get(ye.field))
            if xv is not None and yv is not None:
                pts.append((xv, yv, r.get(ce.field) if ce else None))
        if not pts:
            return self._empty(spec, theme)
        groups: list[Any] = []
        for _, _, c in pts:
            if c not in groups:
                groups.append(c)
        color = {g: _COLORS[i % len(_COLORS)] for i, g in enumerate(groups[:10])}
        w, h = float(max(spec.width, 200)), float(max(spec.height, 160))
        top = 40.0 if spec.title else 16.0
        legend_svg = ""
        if ce and len(groups) > 1 and spec.show_legend:
            series = [_Series(self._cat(spec, g), [], color[g]) for g in groups[:10]]
            legend_svg, lh = self._legend(series, 16, top + 4, w - 32, theme)
            top += lh + 4
        xs = [p[0] for p in pts]
        ysv = [p[1] for p in pts]
        x0, x1 = _yrange(xs)
        y0, y1 = _yrange(ysv)
        xt, yt = _ticks(x0, x1, 5), _ticks(y0, y1, 5)
        x0, x1 = min(x0, xt[0]), max(x1, xt[-1])
        y0, y1 = min(y0, yt[0]), max(y1, yt[-1])
        ylabels = [self._fmt(spec, t, axis=True) for t in yt]
        left = 16 + max(len(t) for t in ylabels) * 6.6 + 22
        bottom, right = 44.0, 16.0
        pw, ph = w - left - right, h - top - bottom

        def px(v: float) -> float:
            return left + (v - x0) / (x1 - x0) * pw

        def py(v: float) -> float:
            return top + ph - (v - y0) / (y1 - y0) * ph

        out = self._open(spec, w, h, theme) + legend_svg
        for t, lbl in zip(yt, ylabels, strict=True):
            if y0 <= t <= y1:
                out += (
                    f'<line x1="{_f(left)}" y1="{_f(py(t))}" x2="{_f(left + pw)}" y2="{_f(py(t))}"'
                    f' stroke="{theme["grid"]}"/><text x="{_f(left - 6)}" y="{_f(py(t))}"'
                    f' text-anchor="end" dominant-baseline="central" font-size="10"'
                    f' fill="{theme["muted"]}">{_xml(lbl)}</text>'
                )
        for t in xt:
            if x0 <= t <= x1:
                out += (
                    f'<line x1="{_f(px(t))}" y1="{_f(top)}" x2="{_f(px(t))}" y2="{_f(top + ph)}"'
                    f' stroke="{theme["grid"]}"/><text x="{_f(px(t))}" y="{_f(top + ph + 14)}"'
                    f' text-anchor="middle" font-size="10" fill="{theme["muted"]}">'
                    f"{_xml(self._fmt(spec, t, axis=True))}</text>"
                )
        out += (
            f'<text x="{_f(left + pw / 2)}" y="{_f(h - 8)}" text-anchor="middle" font-size="11"'
            f' fill="{theme["muted"]}">{_xml(xe.label or xe.field)}</text>'
        )
        cy = top + ph / 2
        out += (
            f'<text x="14" y="{_f(cy)}" transform="rotate(-90 14 {_f(cy)})" text-anchor="middle"'
            f' font-size="11" fill="{theme["muted"]}">{_xml(ye.label or ye.field)}</text>'
        )
        for x, y, c in pts[:5000]:
            tip = (
                f"{xe.label or xe.field}: {self._fmt(spec, x)}, "
                f"{ye.label or ye.field}: {self._fmt(spec, y)}"
            )
            if ce:
                tip = f"{self._cat(spec, c)} · " + tip
            out += (
                f'<circle cx="{_f(px(x))}" cy="{_f(py(y))}" r="3.5"'
                f' fill="{color.get(c, _COLORS[0])}" fill-opacity="0.75">'
                f"<title>{_xml(tip)}</title></circle>"
            )
        return out + "</svg>"

    # ------------------------------------------------------------------
    # Pie / donut
    # ------------------------------------------------------------------

    def _pie(self, spec: ViewSpec, rows: list[dict[str, Any]], theme: dict[str, str]) -> str:
        ce = spec.encoding_for(EncodingChannel.COLOR) or spec.encoding_for(EncodingChannel.X)
        ye = spec.encoding_for(EncodingChannel.Y)
        if not ce or not ye:
            return self._empty(spec, theme)
        slices: list[tuple[str, float]] = []
        for row in rows:
            v = _num_or_none(row.get(ye.field))
            if v is not None and v > 0:
                slices.append((self._cat(spec, row.get(ce.field)), v))
        if not slices:
            return self._empty(spec, theme)
        slices.sort(key=lambda s: -s[1])
        if len(slices) > 8:
            other = sum(v for _, v in slices[7:])
            slices = [*slices[:7], ("Other", other)]
        total = sum(v for _, v in slices)
        w, h = float(max(spec.width, 200)), float(max(spec.height, 160))
        top = 40.0 if spec.title else 16.0
        legend_w = min(w * 0.45, 240.0)
        size = min(w - legend_w - 32, h - top - 16)
        r = max(size / 2, 20)
        cx, cy = 16 + r, top + (h - top - 16) / 2
        out = self._open(spec, w, h, theme)
        angle = -math.pi / 2
        for i, (name, v) in enumerate(slices):
            frac = v / total
            color = _COLORS[i % len(_COLORS)]
            tip = f"{name}: {self._fmt(spec, v)} ({frac:.1%})"
            if frac >= 0.9999:
                out += (
                    f'<circle cx="{_f(cx)}" cy="{_f(cy)}" r="{_f(r)}" fill="{color}">'
                    f"<title>{_xml(tip)}</title></circle>"
                )
            else:
                a2 = angle + frac * 2 * math.pi
                large = 1 if frac > 0.5 else 0
                x1, y1 = cx + r * math.cos(angle), cy + r * math.sin(angle)
                x2, y2 = cx + r * math.cos(a2), cy + r * math.sin(a2)
                out += (
                    f'<path d="M{_f(cx)},{_f(cy)} L{_f(x1)},{_f(y1)} A{_f(r)},{_f(r)} 0 {large} 1'
                    f' {_f(x2)},{_f(y2)} Z" fill="{color}" stroke="{theme["bg"]}"'
                    f' stroke-width="1.5"><title>{_xml(tip)}</title></path>'
                )
                angle = a2
        out += f'<circle cx="{_f(cx)}" cy="{_f(cy)}" r="{_f(r * 0.55)}" fill="{theme["bg"]}"/>'
        out += (
            f'<text x="{_f(cx)}" y="{_f(cy - 6)}" text-anchor="middle" font-size="16"'
            f' font-weight="600" fill="{theme["text"]}">{_xml(self._fmt(spec, total, axis=True))}'
            f'</text><text x="{_f(cx)}" y="{_f(cy + 12)}" text-anchor="middle" font-size="10"'
            f' fill="{theme["muted"]}">Total</text>'
        )
        lx = cx + r + 24
        ly = cy - len(slices) * 10 + 6
        for i, (name, v) in enumerate(slices):
            yy = ly + i * 20
            out += (
                f'<rect x="{_f(lx)}" y="{_f(yy - 9)}" width="10" height="10" rx="2"'
                f' fill="{_COLORS[i % len(_COLORS)]}"/><text x="{_f(lx + 16)}" y="{_f(yy)}"'
                f' font-size="11" fill="{theme["text"]}">{_xml(_truncate(name, 22))}'
                f'<tspan fill="{theme["muted"]}"> {v / total:.0%}</tspan></text>'
            )
        return out + "</svg>"

    # ------------------------------------------------------------------
    # KPI
    # ------------------------------------------------------------------

    def _kpi(self, spec: ViewSpec, rows: list[dict[str, Any]], theme: dict[str, str]) -> str:
        ye = spec.encoding_for(EncodingChannel.Y)
        field = ye.field if ye else next(iter(rows[0]), None)
        if field is None:
            return self._empty(spec, theme)
        value = rows[0].get(field)
        label = (ye.label if ye and ye.label else None) or spec.title or field
        w, h = float(max(spec.width, 200)), float(max(spec.height, 100))
        text = self._fmt(spec, value)
        size = min(h * 0.38, (w - 32) / max(len(text) * 0.6, 1), 72)
        spec_no_title = spec.model_copy(update={"title": None})
        return (
            self._open(spec_no_title, w, h, theme)
            + f'<text x="{_f(w / 2)}" y="{_f(h / 2 - size * 0.15)}" text-anchor="middle"'
            f' dominant-baseline="central" font-size="{_f(size)}" font-weight="650"'
            f' fill="{theme["text"]}">{_xml(text)}</text>'
            f'<text x="{_f(w / 2)}" y="{_f(h / 2 + size * 0.55 + 4)}" text-anchor="middle"'
            f' font-size="13" fill="{theme["muted"]}">{_xml(_truncate(str(label), 60))}</text>'
            "</svg>"
        )

    # ------------------------------------------------------------------
    # Table
    # ------------------------------------------------------------------

    def _table(self, spec: ViewSpec, rows: list[dict[str, Any]], theme: dict[str, str]) -> str:
        enc_fields = [e.field for e in spec.encodings if e.field in rows[0]]
        cols = list(dict.fromkeys(enc_fields)) or list(rows[0].keys())
        cols = cols[:12]
        shown = rows[:200]
        numeric = {
            c: all(isinstance(r.get(c), (int, float)) or r.get(c) is None for r in shown)
            and not all(isinstance(r.get(c), bool) for r in shown if r.get(c) is not None)
            for c in cols
        }
        cells = [
            [self._fmt(spec, r.get(c)) if numeric[c] else self._cat(spec, r.get(c)) for c in cols]
            for r in shown
        ]
        widths = []
        for ci, c in enumerate(cols):
            longest = max([len(str(c))] + [len(row[ci]) for row in cells])
            widths.append(min(max(longest * 7.0 + 20, 60), 260))
        tw = sum(widths)
        rh, hh = 24.0, 28.0
        top = 40.0 if spec.title else 10.0
        w = max(float(spec.width), tw + 20)
        h = max(float(spec.height), top + hh + len(cells) * rh + 10)
        out = self._open(spec, w, h, theme)
        out += (
            f'<rect x="10" y="{_f(top)}" width="{_f(tw)}" height="{_f(hh)}"'
            f' fill="{theme["stripe"]}" stroke="{theme["axis"]}"/>'
        )
        x = 10.0
        for ci, c in enumerate(cols):
            anchor, tx = ("end", x + widths[ci] - 8) if numeric[c] else ("start", x + 8)
            out += (
                f'<text x="{_f(tx)}" y="{_f(top + hh / 2)}" text-anchor="{anchor}"'
                f' dominant-baseline="central" font-size="12" font-weight="bold"'
                f' fill="{theme["text"]}">{_xml(_truncate(str(c), int(widths[ci] / 7)))}</text>'
            )
            x += widths[ci]
        for ri, row in enumerate(cells):
            y = top + hh + ri * rh
            bg = theme["stripe"] if ri % 2 else theme["bg"]
            out += (
                f'<rect x="10" y="{_f(y)}" width="{_f(tw)}" height="{_f(rh)}" fill="{bg}"'
                f' stroke="{theme["grid"]}"/>'
            )
            x = 10.0
            for ci, val in enumerate(row):
                anchor, tx = ("end", x + widths[ci] - 8) if numeric[cols[ci]] else ("start", x + 8)
                out += (
                    f'<text x="{_f(tx)}" y="{_f(y + rh / 2)}" text-anchor="{anchor}"'
                    f' dominant-baseline="central" font-size="11" fill="{theme["text"]}">'
                    f"{_xml(_truncate(val, int(widths[ci] / 6.5)))}</text>"
                )
                x += widths[ci]
        return out + "</svg>"


# ------------------------------------------------------------------
# Pure functions
# ------------------------------------------------------------------


def _num_or_none(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        return None if math.isnan(f) or math.isinf(f) else f
    try:
        return float(str(value).replace(",", "").replace("$", ""))
    except ValueError:
        return None


def _to_num(value: object) -> float:
    n = _num_or_none(value)
    return 0.0 if n is None else n


def _yrange(vals: list[float]) -> tuple[float, float]:
    if not vals:
        return (0, 1)
    vmin, vmax = min(vals), max(vals)
    if vmin == vmax:
        return (max(0, vmin - 1) if vmin >= 0 else vmin - 1, vmin + 1)
    pad = (vmax - vmin) * 0.05
    return (vmin - pad, vmax + pad)


def _ticks(ymin: float, ymax: float, n: int = 5) -> list[float]:
    """Nice, evenly spaced tick values covering [ymin, ymax]."""
    if ymin == ymax:
        return [ymin]
    span = ymax - ymin
    raw = span / max(n, 1)
    mag = 10 ** math.floor(math.log10(raw))
    res = raw / mag
    nice = (1 if res <= 1.5 else 2 if res <= 3.5 else 5 if res <= 7.5 else 10) * mag
    start = math.floor(ymin / nice) * nice
    ticks: list[float] = []
    cur = start
    while cur <= ymax + nice * 1e-9 or len(ticks) < 2:
        ticks.append(round(cur, 10))
        cur += nice
        if len(ticks) > 50:  # pragma: no cover - defensive
            break
    if ticks[-1] < ymax:
        ticks.append(round(cur, 10))
    return ticks
