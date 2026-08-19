"""HTTP middleware and local-only CORS policy for the API interface."""

from __future__ import annotations

import hmac
import ipaddress
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from fnirs_flow.settings import Settings

MAX_BODY_BYTES = 10 * 1024 * 1024
PUBLIC_PATHS = {"/api/health", "/docs", "/openapi.json", "/redoc"}
DEFAULT_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8000",
]
CallNext = Callable[[Request], Awaitable[Response]]


def is_loopback_host(host: str | None) -> bool:
    """Return whether a client host is local, including the test client."""
    if not host:
        return True
    normalized = host.strip().lower()
    if normalized in {"localhost", "testclient"} or normalized.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def validate_cors_origin(origin: str) -> bool:
    """Allow only explicit local HTTP(S) origins."""
    if origin == "*":
        return False
    try:
        parsed = urlparse(origin)
        hostname = parsed.hostname or ""
        return parsed.scheme in {"http", "https"} and (
            hostname in {"localhost", "127.0.0.1", "::1"} or hostname.endswith(".localhost")
        )
    except (ValueError, AttributeError):
        return False


def configured_cors_origins(settings: Settings) -> list[str]:
    raw = settings.cors_origins or tuple(DEFAULT_CORS_ORIGINS)
    origins = [value for value in raw if validate_cors_origin(value)]
    return origins or list(DEFAULT_CORS_ORIGINS)


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                body_size = int(content_length)
            except ValueError:
                return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length header"})
            if body_size > MAX_BODY_BYTES:
                return JSONResponse(status_code=413, content={"detail": "Request body too large (max 10MB)"})
        return await call_next(request)


class LocalOnlyWithoutAPIKeyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, api_key: str) -> None:
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        if self.api_key or request.url.path in PUBLIC_PATHS:
            return await call_next(request)
        host = request.client.host if request.client else None
        if not is_loopback_host(host):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": (
                        "Remote API access requires FNIRS_API_KEY. "
                        "Bind to localhost or set FNIRS_API_KEY before exposing the server."
                    )
                },
            )
        return await call_next(request)


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, api_key: str) -> None:
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        api_key = self.api_key
        if not api_key or request.url.path in PUBLIC_PATHS:
            return await call_next(request)
        if not hmac.compare_digest(request.headers.get("x-api-key", ""), api_key):
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
        return await call_next(request)


def configure_http_middleware(app: FastAPI, settings: Settings) -> None:
    """Register middleware in the same effective order as the legacy app module."""
    app.add_middleware(RequestSizeLimitMiddleware)
    app.add_middleware(LocalOnlyWithoutAPIKeyMiddleware, api_key=settings.api_key)
    app.add_middleware(APIKeyAuthMiddleware, api_key=settings.api_key)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=configured_cors_origins(settings),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
    )
