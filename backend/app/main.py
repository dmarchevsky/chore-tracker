"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app import obs
from app.api.v1 import api_router
from app.auth.cf_access import CfAccessMiddleware
from app.config import get_settings

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    # Full CSP/HSTS are terminated at the proxy in Phase 6; these are the app-level floor.
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; object-src 'none'",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        for key, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        if get_settings().is_prod:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload"
            )
        return response


def create_app() -> FastAPI:
    obs.configure_logging()
    settings = get_settings()
    app = FastAPI(
        title="ChoreKeeper API",
        version="0.1.0",
        docs_url=None if settings.is_prod else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_prod else "/openapi.json",
    )
    app.add_middleware(SecurityHeadersMiddleware)
    # Added last = runs first (outermost). Order: TrustedHost -> CfAccess -> headers.
    if settings.cf_access_team_domain and settings.cf_access_aud:
        app.add_middleware(
            CfAccessMiddleware,
            team_domain=settings.cf_access_team_domain,
            aud=settings.cf_access_aud,
        )
    if settings.allowed_hosts:
        hosts = [h.strip() for h in settings.allowed_hosts.split(",") if h.strip()]
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=[*hosts, "localhost", "127.0.0.1", "testserver"],
        )
    app.include_router(api_router)
    return app


app = create_app()
