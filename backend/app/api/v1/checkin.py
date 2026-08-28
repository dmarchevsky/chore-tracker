"""Per-kid geofence check-in webhook (spec §6.2, §10 `POST /checkin/{token}`).

Unauthenticated by design — the token *is* the credential. Rate-limited to 20/hour and
scoped to transitioning a single OPEN location occurrence; assume the token leaks.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.auth import ratelimit
from app.auth.deps import DbDep
from app.schemas.submission import GeoIn
from app.services import checkin

router = APIRouter(prefix="/checkin", tags=["checkin"])


@router.post("/{token}")
async def webhook_checkin(token: str, payload: GeoIn, request: Request, db: DbDep) -> dict:
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
