"""FastAPI application factory."""

from __future__ import annotations

import json
import logging
import re

from fastapi import FastAPI
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app import obs
from app.api.v1 import api_router
from app.auth.cf_access import CfAccessMiddleware
from app.config import DEFAULT_SESSION_SECRET, get_settings

log = logging.getLogger("chorekeeper.api")

# Anything whose name looks like a credential never reaches the log. /auth/login carries the
# break-glass password, and a malformed login body would otherwise be written in clear.
_SECRET_KEY = re.compile(r"password|token|secret|api_key", re.I)
_MAX_LOGGED_BODY = 2000


async def _redacted_body(request: Request) -> str | None:
    """The request body with credentials masked, or None when it should not be logged."""
    if not request.headers.get("content-type", "").startswith("application/json"):
        return None  # multipart photo uploads: never log the bytes
    try:
        raw = await request.body()  # already cached by FastAPI before the handler runs
        if not raw:
            return None
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            parsed = {k: ("***" if _SECRET_KEY.search(k) else v) for k, v in parsed.items()}
        return json.dumps(parsed, default=str)[:_MAX_LOGGED_BODY]
    except Exception:
        return "<unparsable>"


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
    #
    # DEV_AUTH hands out a session to anyone who names a user, so it and Access are mutually
    # exclusive and a prod app carrying it must not start at all. Refusing here — before the
    # port is bound — is the only check that cannot be missed: a running-but-open ChoreKeeper
    # looks exactly like a working one from the outside.
    if settings.dev_auth and settings.is_prod:
        raise RuntimeError(
            "DEV_AUTH is on with ENVIRONMENT=prod: that is passwordless sign-in on a "
            "production stack. Unset DEV_AUTH, or run the dev compose file."
        )
    # The session secret signs the session cookie's server-side lookup AND the short-lived
    # media URLs (services/media.py). Its default is published in this repo, so a prod app
    # running on it hands out forgeable media links — and, like DEV_AUTH, looks completely
    # healthy from the outside. Compose guards this with ${SESSION_SECRET:?}, which covers
    # the compose path only; this covers every other way the app gets started.
    if settings.is_prod and settings.session_secret == DEFAULT_SESSION_SECRET:
        raise RuntimeError(
            "SESSION_SECRET is still the development default under ENVIRONMENT=prod. "
            "Generate one (openssl rand -hex 32) and set it in env.production."
        )
    if settings.cf_access_team_domain and settings.cf_access_aud:
        if settings.dev_auth:
            raise RuntimeError(
                "DEV_AUTH is on with CF_ACCESS_* set: pick one identity source, not both."
            )
        app.add_middleware(
            CfAccessMiddleware,
            team_domain=settings.cf_access_team_domain,
            aud=settings.cf_access_aud,
            issuer=settings.cf_access_issuer,
        )
    if settings.allowed_hosts:
        hosts = [h.strip() for h in settings.allowed_hosts.split(",") if h.strip()]
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=[*hosts, "localhost", "127.0.0.1", "testserver"],
        )
    app.include_router(api_router)

    @app.exception_handler(RequestValidationError)
    async def _log_invalid_request(request: Request, exc: RequestValidationError) -> Response:
        """Record *why* a 422 happened. Without this the client sees a field error and the
        server keeps no record at all, which is how a save failure becomes unexplainable.

        Not the audit logger — that stream is the money/override trail (spec §5) and must not
        fill with validation noise. The response is delegated so its shape is unchanged.
        """
        log.warning(
            "request validation failed",
            extra={
                "event": "request.invalid",
                "path": request.url.path,
                "method": request.method,
                "errors": exc.errors(),
                "body": await _redacted_body(request),
            },
        )
        return await request_validation_exception_handler(request, exc)

    return app


app = create_app()
