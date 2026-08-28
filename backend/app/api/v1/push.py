"""Web Push subscription management (spec §4.5, §10 `POST /push/subscribe`)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select

from app.auth.deps import CurrentUser, DbDep
from app.config import get_settings
from app.models import PushSubscription

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
