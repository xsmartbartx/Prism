"""FastAPI application factory."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.errors import (
    BindingError,
    ConnectorError,
    DriftDetected,
    PolicyViolation,
    PrismError,
    ValidationError,
)
from data.query.duck import QueryTimeout
from server import __version__
from server.config import Settings, get_settings
from server.container import Services
from server.db import Database
from server.db.migrate import upgrade
from server.errors import (
    BadRequest,
    Conflict,
    Forbidden,
    LimitExceeded,
    NotFound,
    TooManyRequests,
    Unauthorized,
)
from server.logging import configure_logging

log = logging.getLogger("prism")

_STATUS: list[tuple[type[PrismError], int]] = [
    (NotFound, 404),
    (Unauthorized, 401),
    (Forbidden, 403),
    (PolicyViolation, 403),
    (Conflict, 409),
    (LimitExceeded, 402),
    (TooManyRequests, 429),
    (DriftDetected, 422),
    (QueryTimeout, 504),
    (BadRequest, 400),
    (ValidationError, 400),
    (BindingError, 400),
    (ConnectorError, 400),
]

_CSP = (
    "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; connect-src 'self'; font-src 'self' data:; object-src 'none'; "
    "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)
_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def find_static_dir(settings: Settings) -> Path | None:
    candidates = [settings.static_dir] if settings.static_dir else []
    here = Path(__file__).resolve().parent
    candidates += [here / "static", here.parent / "web" / "dist"]
    for c in candidates:
        if c and (c / "index.html").exists():
            return c
    return None


def create_app(settings: Settings | None = None, *, db: Database | None = None) -> FastAPI:
    settings = settings or get_settings()
    if settings.env != "test":
        configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        svc: Services = app.state.services
        upgrade(svc.db)
        with svc.db.transaction() as s:
            svc.auth.purge_expired(s)
        if (
            settings.env == "production"
            and settings.base_url.startswith("http://")
            and not any(h in settings.base_url for h in ("localhost", "127.0.0.1"))
        ):
            log.warning(
                "PRISM_BASE_URL is plain http; sessions are not protected by TLS. "
                "Put Prism behind HTTPS (see deploy/compose.yml) and set an https:// base URL."
            )
        log.info("Prism %s ready on %s", __version__, settings.base_url)
        yield
        svc.db.dispose()

    app = FastAPI(
        title="Prism API",
        version=__version__,
        description=(
            "Self-hosted data platform: import files, query datasets, render charts and "
            "share them. Authenticate with a session cookie (web app) or "
            "`Authorization: Bearer prism_…` API key."
        ),
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.services = Services.build(settings, db)

    # ------------------------------------------------------------------
    # Middleware: request id, logging, CSRF, security headers
    # ------------------------------------------------------------------

    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        start = time.perf_counter()
        path = request.url.path
        if (
            request.method in _UNSAFE
            and path.startswith("/api/")
            and not request.headers.get("authorization")
            and request.headers.get("x-prism-csrf") != "1"
        ):
            response: Response = _error(403, "CsrfRejected", "Missing X-Prism-CSRF header")
        else:
            try:
                response = await call_next(request)
            except Exception:
                log.exception("Unhandled error", extra={"request_id": rid, "path": path})
                response = _error(500, "InternalError", "Something went wrong. Request id: " + rid)
        response.headers["X-Request-Id"] = rid
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if "Content-Security-Policy" not in response.headers:
            response.headers["Content-Security-Policy"] = (
                _CSP.replace("script-src 'self'", "script-src 'self' 'unsafe-inline'")
                if path.startswith("/api/docs")
                else _CSP
            )
        if response.headers.get("X-Frame-Options") == "":
            del response.headers["X-Frame-Options"]
        else:
            response.headers.setdefault("X-Frame-Options", "DENY")
        if settings.base_url.startswith("https://"):
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        if path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        log.info(
            "%s %s %s",
            request.method,
            path,
            response.status_code,
            extra={
                "request_id": rid,
                "method": request.method,
                "path": path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                "user": getattr(request.state, "user", None),
            },
        )
        return response

    # ------------------------------------------------------------------
    # Errors
    # ------------------------------------------------------------------

    @app.exception_handler(PrismError)
    async def prism_error(_: Request, exc: PrismError) -> JSONResponse:
        status = next((code for cls, code in _STATUS if isinstance(exc, cls)), 400)
        return _error(status, exc.code, str(exc))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errs = exc.errors()
        first = errs[0] if errs else {}
        loc = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
        msg = first.get("msg", "Invalid request")
        return JSONResponse(
            {
                "error": {
                    "code": "InvalidRequest",
                    "message": f"{loc}: {msg}" if loc else msg,
                    "details": [{"loc": e.get("loc"), "msg": e.get("msg")} for e in errs[:10]],
                }
            },
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error(exc.status_code, "HttpError", str(exc.detail))

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    from server.api.routes import (
        admin,
        auth,
        charts,
        datasets,
        imports,
        public,
        system,
        workspace,
    )

    for r in (
        system.router,
        auth.router,
        workspace.router,
        imports.router,
        datasets.router,
        charts.router,
        admin.router,
        public.router,
    ):
        app.include_router(r)

    static = find_static_dir(settings)
    if static is not None:
        index = static / "index.html"

        @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
        async def spa(path: str) -> Response:
            if path.startswith(("api/", "s/", "embed/")):
                return _error(404, "NotFound", "Not found")
            target = (static / path).resolve()
            if path and static.resolve() in target.parents and target.is_file():
                cache = (
                    "public, max-age=31536000, immutable"
                    if path.startswith("assets/")
                    else "no-cache"
                )
                return FileResponse(target, headers={"Cache-Control": cache})
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
    else:

        @app.get("/", include_in_schema=False)
        async def root() -> JSONResponse:
            return JSONResponse(
                {
                    "name": "Prism",
                    "version": __version__,
                    "docs": "/api/docs",
                    "note": "Web UI not built. Run `npm run build` in web/.",
                }
            )

    return app
