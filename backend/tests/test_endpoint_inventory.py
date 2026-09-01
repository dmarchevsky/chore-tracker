"""Endpoint auth inventory (spec §12.1 / Phase 6 acceptance).

A security scan must show **no unauthenticated endpoint** other than the deliberate,
documented exceptions below. This test enforces that statically: every mounted route
either resolves `current_auth` (session cookie + CSRF on writes) somewhere in its
dependency tree, or is named in `PUBLIC_ROUTES` with a reason.

If you add a route, this test fails until you either wire auth into it or add it here
with a justification — that's the point.
"""

from __future__ import annotations

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, iter_route_contexts

from app.auth.deps import current_auth
from app.main import app

# path -> why it is reachable without a session
PUBLIC_ROUTES: dict[str, str] = {
    "/api/v1/health": "liveness probe (spec §10)",
    "/api/v1/auth/login": (
        "break-glass admin password; loopback only — the Caddy front door 404s it "
        "(spec §12.1). IP + per-account rate limited."
    ),
    "/api/v1/auth/logout": "clears the session cookie; no side effects, safe to call anon",
    "/api/v1/auth/me": (
        "SPA bootstrap probe, and the sign-in itself: behind Cloudflare Access the "
        "verified Google address becomes a session (spec §12.1). 401 without either."
    ),
    "/api/v1/checkin/{token}": "per-kid bearer token, rate limited 20/h (spec §6.2)",
    "/api/v1/submissions/{submission_id}/media/{idx}": (
        "HMAC-signed 5-min URL or a valid session (spec §5, §10)"
    ),
}


def _walk(dep: Dependant):
    yield dep
    for sub in dep.dependencies:
        yield from _walk(sub)


def _api_routes() -> list[tuple[str, APIRoute]]:
    routes = [
        (ctx.path, ctx.original_route)
        for ctx in iter_route_contexts(app.routes)
        if isinstance(ctx.original_route, APIRoute)
    ]
    # Guard against a FastAPI internals change silently yielding nothing.
    assert len(routes) > 20, f"route enumeration looks broken: {len(routes)} routes"
    return routes


def _resolves_auth(route: APIRoute) -> bool:
    return any(d.call is current_auth for d in _walk(route.dependant))


def test_every_route_requires_auth_or_is_documented_public():
    offenders: list[str] = []
    for path, route in _api_routes():
        if _resolves_auth(route) or path in PUBLIC_ROUTES:
            continue
        offenders.append(f"{sorted(route.methods)} {path}")
    assert not offenders, "undocumented unauthenticated route(s): " + "; ".join(offenders)


def test_public_route_list_has_no_stale_entries():
    live = {path for path, _ in _api_routes()}
    stale = [p for p in PUBLIC_ROUTES if p not in live]
    assert not stale, f"PUBLIC_ROUTES lists routes that no longer exist: {stale}"
