"""Cloudflare Access — the app's only remote identity source (spec §12.1, §12.2).

When ``CF_ACCESS_TEAM_DOMAIN`` + ``CF_ACCESS_AUD`` are set, every request under
``/api/v1/`` must carry a valid ``Cf-Access-Jwt-Assertion`` — the JWT Cloudflare Access
injects once the visitor has signed in with Google. The verified claims are stashed on
``request.state.cf_access`` so ``/auth/me`` can turn the ``email`` claim into a session
without verifying the token a second time.

Three paths are exempt, each for a reason that has to survive a re-read:

* ``/api/v1/health`` — the container liveness probe, which has no browser to redirect.
* ``/api/v1/checkin/{token}`` — the iOS Shortcuts geofence webhook. A Shortcut cannot
  carry an Access session, so this path gets a Cloudflare *Bypass* policy; it is
  authenticated by the per-kid token and rate-limited instead (spec §6.2).
* ``/api/v1/auth/login`` — the break-glass admin password. The tunnel's Caddy site answers
  404 for it; only the LAN site carries it.

The **LAN door** is exempt wholesale. Without that, break-glass would be theatre: the login
succeeds and then every other endpoint refuses the session it just issued, so the documented
way back in when Cloudflare or Google is down does not actually lead anywhere. Caddy stamps
every proxied request with ``X-CK-Door``, overwriting whatever the client sent; the api is
reachable from nothing but those two Caddy sites and the host's own loopback, so an internet
request always arrives stamped ``tunnel``. Enforcement is the default and only an explicit
``lan`` skips it, so a missing or unrecognised value fails closed.

Never trust ``CF-Access-Authenticated-User-Email``: it is a plain header that anything
able to reach the origin can set. Only the signature-verified ``email`` claim counts.

Unset config → no-op (LAN dev, tests).
"""

from __future__ import annotations

import logging
from typing import Any

import jwt
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

log = logging.getLogger("chorekeeper.api")

_HEADER = "cf-access-jwt-assertion"

_EXEMPT_EXACT = {"/api/v1/health", "/api/v1/auth/login"}
_EXEMPT_PREFIX = ("/api/v1/checkin/",)

_DOOR_HEADER = "x-ck-door"
_LAN_DOOR = "lan"


def _guarded(path: str) -> bool:
    if not path.startswith("/api/v1/"):
        return False
    if path.rstrip("/") in _EXEMPT_EXACT:
        return False
    return not path.startswith(_EXEMPT_PREFIX)


class CfAccessMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, team_domain: str, aud: str, issuer: str = "") -> None:
        super().__init__(app)
        # Normally the issuer is the team domain. It stops being so the moment a Zero Trust
        # team is renamed: Cloudflare serves login and JWKS from the new name but keeps
        # putting the ORIGINAL name in `iss`, and the old hostname 404s — so the issuer has
        # to be settable on its own rather than derived. Comma-separated, because a rename
        # can also flip it back and accepting both avoids a second outage.
        self._issuers = [i.strip() for i in issuer.split(",") if i.strip()] or [
            f"https://{team_domain}"
        ]
        # One AUD tag per Access application, and the deployment runs more than one (the
        # whole-host app and the stricter admin-scoped app), so this is a list.
        self._aud = [a.strip() for a in aud.split(",") if a.strip()]
        self._jwks = jwt.PyJWKClient(
            f"https://{team_domain}/cdn-cgi/access/certs", cache_keys=True, lifespan=600
        )

    def _verify(self, token: str) -> dict[str, Any]:
        key = self._jwks.get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=self._aud,
            options={"require": ["iss", "aud", "exp"]},
        )
        # Checked here rather than via PyJWT's `issuer=` so more than one is accepted.
        if claims["iss"] not in self._issuers:
            raise jwt.InvalidIssuerError("Invalid issuer")
        return claims

    def _log_rejection(self, request: Request, token: str, exc: Exception) -> None:
        """Say what the token actually claimed, not just that it was wrong.

        PyJWT reports "Invalid issuer"/"Invalid audience" without naming either side, which
        leaves an operator comparing a config value against a token they cannot read. These
        are our own org's identifiers, so logging them (server-side only, never in the
        response) costs nothing and turns a guessing game into one line.
        """
        claims = _unverified(token)
        log.warning(
            "rejected a Cloudflare Access assertion",
            extra={
                "event": "cf_access.rejected",
                "path": request.url.path,
                "error": str(exc),
                "token_iss": claims.get("iss"),
                "token_aud": claims.get("aud"),
                "expected_iss": self._issuers,
                "expected_aud": self._aud,
            },
        )

    async def dispatch(self, request: Request, call_next) -> Response:
        if not _guarded(request.url.path):
            return await call_next(request)
        if is_lan_door(request):
            # The LAN door. Cloudflare is not in front of it and cannot be, which is the
            # whole point of it existing (spec §12.1). App auth still applies to every
            # route behind this — the session cookie and CSRF checks are untouched.
            return await call_next(request)
        token = request.headers.get(_HEADER)
        if not token:
            # The line that separates "reached us without an assertion" from "never reached
            # us at all" — the two look identical from the app, and only one of them is
            # Cloudflare's problem. INFO: any unauthenticated request lands here, though
            # behind Access essentially none get this far.
            log.info(
                "request carried no Cloudflare Access assertion",
                extra={"event": "cf_access.missing", "path": request.url.path},
            )
            return JSONResponse(
                {"detail": "Cloudflare Access authentication required"}, status_code=403
            )
        try:
            claims = await run_in_threadpool(self._verify, token)
        except jwt.PyJWTError as exc:
            self._log_rejection(request, token, exc)
            return JSONResponse(
                {"detail": f"invalid Cloudflare Access token: {exc}"}, status_code=403
            )
        request.state.cf_access = claims
        return await call_next(request)


def is_lan_door(request: Request) -> bool:
    """True when Caddy stamped this request as arriving through the LAN door.

    Enforcement is the default and only an exact "lan" skips it, so a stripped, misspelled
    or absent value fails closed. Trustworthy because the api is reachable from nothing but
    the two Caddy sites and the host's own loopback, and each site sets this header
    unconditionally, overwriting whatever the client sent.
    """
    return request.headers.get(_DOOR_HEADER) == _LAN_DOOR


def _unverified(token: str) -> dict[str, Any]:
    """The token's claims WITHOUT verifying anything. Diagnostics only — never trusted."""
    try:
        return jwt.decode(token, options={"verify_signature": False})
    except Exception:
        return {}


def access_email(request: Request) -> str | None:
    """The Google address Access verified for this request, lowercased, or None."""
    claims = getattr(request.state, "cf_access", None)
    email = (claims or {}).get("email") if isinstance(claims, dict) else None
    return email.strip().lower() if isinstance(email, str) and email.strip() else None
