"""Per-kid geofence check-in webhook (spec §6.2, §10 `POST /checkin/{token}`).

Unauthenticated by design — the token *is* the credential. Scoped to transitioning a
single OPEN location occurrence; assume the token leaks.

Two limits, because they stop different things. The per-token 20/hour caps what a leaked
token can do (spec §6.2). The per-IP limit caps *guessing*: every guess is a fresh token
key, so the per-token bucket never fills and would throttle nothing. Cloudflare Access
bypasses this path by policy, and the WAF rate-limit rule is a console setting that does
not exist on the LAN door at all, so the app cannot be the only place without one.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.auth import ratelimit
from app.auth.deps import DbDep
from app.net import client_ip
from app.schemas.submission import GeoIn
from app.services import checkin

router = APIRouter(prefix="/checkin", tags=["checkin"])


@router.post("/{token}")
async def webhook_checkin(token: str, payload: GeoIn, request: Request, db: DbDep) -> dict:
    if not ratelimit.ip_allowed(client_ip(request)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many attempts, slow down")
    if not ratelimit.token_allowed(token):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many check-ins this hour")
    resolved = await checkin.resolve_token(db, token)
    if resolved is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown or revoked token")
    token_row, child = resolved
    return await checkin.process_checkin(
        db,
        token_row=token_row,
        child=child,
        lat=payload.lat,
        lon=payload.lon,
        accuracy=payload.accuracy,
    )
