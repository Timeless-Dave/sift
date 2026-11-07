"""App factory: middleware, error handling and routers."""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .. import __version__
from ..core.config import Settings, get_settings
from ..core.errors import SiftError
from ..core.logging import request_id, setup_logging
from ..domain import registry
from .deps import Container, client_ip
from .routes import admin, agent, assays, calibration, runs

log = logging.getLogger("sift.http")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "cross-origin",
}


def _error(status: int, code: str, message: str, headers: dict | None = None) -> JSONResponse:
    # `detail` kept for clients written against v0.1.
    return JSONResponse({"error": {"code": code, "message": message, "request_id": request_id.get()},
                         "detail": message}, status_code=status, headers=headers)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.validate()
    registry.load_all()
    setup_logging()
    app = FastAPI(title="Sift Lab API", version=__version__,
                  description="Run food-fraud screening assays from a phone camera or the Sift device. "
                              "Results are screening results; each names the lab method that would confirm it.",
                  # /docs is the Developers tier's API reference, so it stays on in production.
                  # Admin routes are excluded from the schema.
                  docs_url="/docs", redoc_url=None)
    app.state.container = Container.build(settings)

    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                       allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type", "X-Sift-Key",
                                                                               "X-Admin-Token", "X-Request-ID"],
                       expose_headers=["X-Request-ID", "Retry-After"], max_age=600)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id", "")[:64] or uuid.uuid4().hex[:16]
        token = request_id.set(rid)
        start = time.perf_counter()
        try:
            if request.headers.get("content-type", "").split(";")[0].strip() == "application/json":
                raw_len = request.headers.get("content-length", "").strip()
                if raw_len.isdigit() and int(raw_len) > settings.limits.max_json_bytes:
                    mb = settings.limits.max_json_bytes / (1024 * 1024)
                    response = _error(413, "too_large",
                                      f"JSON bodies must be under {mb:g} MB. Send fewer frames per colour.")
                    response.headers["X-Request-ID"] = rid
                    for k, v in SECURITY_HEADERS.items():
                        response.headers.setdefault(k, v)
                    log.info("request", extra={"fields": {
                        "rid": rid, "method": request.method, "path": request.url.path,
                        "status": response.status_code,
                        "ms": round((time.perf_counter() - start) * 1000, 1)}})
                    return response
            response = await call_next(request)
        finally:
            request_id.reset(token)
        response.headers["X-Request-ID"] = rid
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        log.info("request", extra={"fields": {
            "rid": rid, "method": request.method, "path": request.url.path, "status": response.status_code,
            "ms": round((time.perf_counter() - start) * 1000, 1)}})
        return response

    @app.exception_handler(SiftError)
    async def sift_error(_: Request, exc: SiftError):
        headers = {"Retry-After": str(exc.extra["retry_after"])} if "retry_after" in exc.extra else None
        return _error(exc.status, exc.code, exc.message, headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", []) if p not in ("body", "query", "form"))
        return _error(422, "invalid_input", f"{where or 'Request'}: {first.get('msg', 'invalid value')}")

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception):
        log.exception("unhandled error")
        return _error(500, "internal",
                      "Something went wrong on the Sift server. Quote the request id if you report it.")

    @app.get("/health", tags=["meta"])
    def health(request: Request) -> dict:
        c: Container = app.state.container
        c.limiter.hit("catalog", client_ip(request, c), c.settings.limits.rate_catalog)
        return {"ok": True, "version": __version__, "agent": "muse-spark" if c.client.online else "offline",
                "chat_model": settings.chat_model}

    for module in (assays, runs, calibration, agent, admin):
        app.include_router(module.router)
    return app
