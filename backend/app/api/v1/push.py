"""Web Push subscription management (spec §4.5, §10 `POST /push/subscribe`)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select

from app.auth.deps import CurrentUser, DbDep
from app.config import get_settings
from app.models import PushSubscription
from app.services import notifications

router = APIRouter(prefix="/push", tags=["push"])


class _Keys(BaseModel):
    p256dh: str
    auth: str


class PushSubscribeIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    endpoint: str = Field(min_length=1)
    keys: _Keys
    expirationTime: float | None = None


@router.get("/vapid-key")
async def vapid_key(user: CurrentUser) -> dict:
    # Authenticated like every other endpoint (spec §12.1 endpoint inventory): the PWA
    # only needs this key after login, right before POST /push/subscribe.
    return {"public_key": get_settings().vapid_public_key}


@router.post("/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def subscribe(
    payload: PushSubscribeIn, request: Request, db: DbDep, user: CurrentUser
) -> None:
    existing = (
        await db.execute(
            select(PushSubscription).where(PushSubscription.endpoint == payload.endpoint)
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.user_id = user.id
        existing.p256dh = payload.keys.p256dh
        existing.auth = payload.keys.auth
        return
    db.add(
        PushSubscription(
            user_id=user.id,
            endpoint=payload.endpoint,
            p256dh=payload.keys.p256dh,
            auth=payload.keys.auth,
            user_agent=(request.headers.get("user-agent") or "")[:256] or None,
        )
    )


@router.delete("/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(endpoint: Annotated[str, Field()], db: DbDep, user: CurrentUser) -> None:
    await db.execute(
        delete(PushSubscription).where(
            PushSubscription.user_id == user.id, PushSubscription.endpoint == endpoint
        )
    )


class PushTestOut(BaseModel):
    """What actually happened, rather than a 204 that proves only that the request arrived."""

    status: str
    devices: int
    error: str | None = None


@router.post("/test")
async def send_test(db: DbDep, user: CurrentUser) -> PushTestOut:
    """Push a notification to the caller's own devices and report the outcome (spec §4.5).

    The failure this exists for is silent: a notification never arrives and there is no way
    to tell an unconfigured server from a revoked permission from a phone that is simply
    slow. `notify` swallows every error by design — the state machine must never block on a
    push — so the log row it returns is the only place the reason exists, and this hands it
    straight back to whoever pressed the button.
    """
    # Counted before the send, so this is how many devices were *tried*: `notify` deletes a
    # subscription the push service reports as gone, and counting after would quietly hide
    # the very device that just failed.
    devices = (
        await db.execute(
            select(func.count())
            .select_from(PushSubscription)
            .where(PushSubscription.user_id == user.id)
        )
    ).scalar_one()
    entry = await notifications.notify(
        db,
        user_id=user.id,
        kind="test",
        title="ChoreKeeper test",
        body="If you can read this, notifications work on this device.",
        url="/admin/settings" if user.is_admin else "/me/settings",
    )
    return PushTestOut(status=entry.status, devices=devices, error=entry.error)
