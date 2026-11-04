"""Public, read-only share pages (/s/<token>) and embeds (/embed/<token>).

Rendered entirely on the server: no JavaScript, no API access, no data
beyond what the shared artifact displays. Every view is counted and an
invalid, expired or revoked token returns the same 404.
"""

from __future__ import annotations

import html
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from core.errors import PrismError
from server.api.deps import services
from server.container import Services
from server.db.models import Chart, Dashboard, Share, Workspace
from server.errors import NotFound
from server.services.artifacts import ArtifactService

router = APIRouter(include_in_schema=False)

_CSS = """
:root{--bg:#f6f8fa;--card:#fff;--text:#1f2328;--muted:#59636e;--border:#d0d7de}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#010409;--card:#0d1117;
--text:#e6edf3;--muted:#9198a1;--border:#30363d}}
:root[data-theme=dark]{--bg:#010409;--card:#0d1117;--text:#e6edf3;--muted:#9198a1;--border:#30363d}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1200px;margin:0 auto;padding:24px 16px}h1{font-size:22px;margin:0 0 4px}
.sub{color:var(--muted);margin:0 0 20px;font-size:13px}
.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:12px}
.tile{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:12px;
overflow:hidden;min-width:0}.tile h2{font-size:14px;margin:0 0 8px}
.tile svg{width:100%;height:auto;display:block}
.single{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:12px}
.single svg{width:100%;height:auto;display:block}
footer{color:var(--muted);font-size:12px;margin-top:20px;text-align:center}
footer a{color:inherit}.err{padding:12px;color:var(--muted);font-size:13px}
@media (max-width:760px){.tile{grid-column:1/-1!important}}
body.embed main{padding:8px;max-width:none}
"""


def _page(title: str, body: str, *, theme: str | None, embed: bool, branding: bool) -> str:
    theme_attr = f' data-theme="{theme if theme in ("light", "dark") else "light"}"'
    footer = (
        "<footer>Made with Prism</footer>"
        if branding
        else ""
    )
    return (
        f'<!doctype html><html lang="en"{theme_attr}><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex,nofollow">'
        f"<title>{html.escape(title)}</title><style>{_CSS}</style></head>"
        f'<body class="{"embed" if embed else ""}"><main>{body}{footer}</main></body></html>'
    )


def _render_tile(svc: Services, s: Session, chart: Chart, theme: str | None) -> str:
    try:
        r = svc.artifacts.render_chart(s, None, chart, theme=theme or "light")
        return r.svg
    except PrismError:
        return '<div class="err">This chart is unavailable.</div>'


def _resolve(svc: Services, s: Session, token: str, *, embed: bool) -> Share:
    from server.services.licensing import current_state

    share = ArtifactService.resolve_share(s, token)
    if embed and (not share.allow_embed or "embed" not in current_state(svc, s).plan.features):
        raise NotFound("Embedding is not enabled for this link")
    return share


def _build(svc: Services, s: Session, share: Share, theme: str | None) -> tuple[str, str]:
    ws = s.get(Workspace, share.workspace_id)
    ws_name = ws.name if ws else ""
    if share.artifact_type == "chart":
        chart = s.get(Chart, share.artifact_id)
        if chart is None:
            raise NotFound("Not found")
        body = (
            f"<h1>{html.escape(chart.name)}</h1>"
            f'<p class="sub">{html.escape(chart.description or ws_name)}</p>'
            f'<div class="single">{_render_tile(svc, s, chart, theme)}</div>'
        )
        return chart.name, body
    dash = s.get(Dashboard, share.artifact_id)
    if dash is None:
        raise NotFound("Not found")
    tiles = []
    for t in sorted(dash.layout, key=lambda t: (t.get("y", 0), t.get("x", 0))):
        chart = s.get(Chart, t["chart_id"])
        if chart is None or chart.workspace_id != share.workspace_id:
            continue
        x, w = int(t.get("x", 0)), int(t.get("w", 6))
        tiles.append(
            f'<section class="tile" style="grid-column:{x + 1}/span {w}">'
            f"<h2>{html.escape(chart.name)}</h2>{_render_tile(svc, s, chart, theme)}</section>"
        )
    body = (
        f"<h1>{html.escape(dash.name)}</h1>"
        f'<p class="sub">{html.escape(dash.description or ws_name)}</p>'
        f'<div class="grid">{"".join(tiles)}</div>'
    )
    return dash.name, body


def _respond(request: Request, token: str, theme: str | None, *, embed: bool) -> Response:
    from server.services.licensing import show_branding

    svc: Services = request.app.state.services
    try:
        with svc.db.transaction() as s:
            share = _resolve(svc, s, token, embed=embed)
            title, body = _build(svc, s, share, theme)
            branding = show_branding(svc, s)
    except NotFound:
        page = _page(
            "Link unavailable",
            "<h1>Link unavailable</h1><p class='sub'>This link is invalid, expired or has been "
            "revoked. Ask the person who shared it for a new one.</p>",
            theme=theme,
            embed=embed,
            branding=False,
        )
        return HTMLResponse(page, status_code=404, headers={"Cache-Control": "no-store"})
    headers: dict[str, Any] = {"Cache-Control": "private, max-age=60"}
    if embed:
        headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors *"
        )
        headers["X-Frame-Options"] = ""
    return HTMLResponse(
        _page(title, body, theme=theme, embed=embed, branding=branding), headers=headers
    )


@router.get("/s/{token}")
def share_page(
    request: Request,
    token: str,
    theme: str | None = Query(default=None, pattern="^(light|dark)$"),
    svc: Services = Depends(services),
) -> Response:
    return _respond(request, token, theme, embed=False)


@router.get("/embed/{token}")
def embed_page(
    request: Request,
    token: str,
    theme: str | None = Query(default=None, pattern="^(light|dark)$"),
    svc: Services = Depends(services),
) -> Response:
    return _respond(request, token, theme, embed=True)
