"""Cloudflare Access enforcement for the admin surface (spec §12.2).

When ``CF_ACCESS_TEAM_DOMAIN`` + ``CF_ACCESS_AUD`` are set, every request to
``/api/v1/admin/*`` (and ``/api/v1/health/llm``) must additionally carry a valid
``Cf-Access-Jwt-Assertion`` — the JWT Cloudflare Access injects after the operator passes
the edge login. This is layered *on top of* the app's own session + TOTP: a tunnel or
Access misconfiguration alone cannot expose admin. Unset config → no-op (LAN/dev).
"""

from __future__ import annotations

import jwt
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_HEADER = "cf-access-jwt-assertion"


def _guarded(path: str) -> bool:
    return path.startswith("/api/v1/admin/") or path == "/api/v1/health/llm"


class CfAccessMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, team_domain: str, aud: str) -> None:
        super().__init__(app)
        self._issuer = f"https://{team_domain}"
        self._aud = aud
        self._jwks = jwt.PyJWKClient(
            f"https://{team_domain}/cdn-cgi/access/certs", cache_keys=True, lifespan=600
        )

    def _verify(self, token: str) -> None:
        key = self._jwks.get_signing_key_from_jwt(token).key
        jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=self._aud,
            issuer=self._issuer,
        )

    async def dispatch(self, request: Request, call_next) -> Response:
        if not _guarded(request.url.path):
            return await call_next(request)
        token = request.headers.get(_HEADER)
        if not token:
            return JSONResponse(
                {"detail": "Cloudflare Access authentication required"}, status_code=403
            )
        try:
            await run_in_threadpool(self._verify, token)
        except jwt.PyJWTError as exc:
            return JSONResponse(
                {"detail": f"invalid Cloudflare Access token: {exc}"}, status_code=403
            )
        return await call_next(request)
