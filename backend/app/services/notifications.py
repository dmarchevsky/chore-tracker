"""Web Push (VAPID) delivery (spec §4.5).

Best-effort: every attempt is logged, a failed push never raises into the state machine,
and a subscription that returns 404/410 is pruned. If VAPID keys are unset the send is
recorded as ``skipped`` and nothing is called.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    Chore,
    ChoreOccurrence,
    NotificationLog,
    PushSubscription,
    User,
    UserRole,
)
from app.models.verification import Verification

log = logging.getLogger("chorekeeper.notifications")


def _vapid_ready() -> bool:
    s = get_settings()
    return bool(s.vapid_private_key and s.vapid_public_key)


def _send_one(sub: PushSubscription, payload: dict) -> None:
    """Sync pywebpush call — run via asyncio.to_thread. Raises on transport failure."""
    from pywebpush import webpush

    s = get_settings()
    webpush(
        subscription_info={
            "endpoint": sub.endpoint,
            "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
        },
        data=json.dumps(payload),
        vapid_private_key=s.vapid_private_key,
        vapid_claims={"sub": f"mailto:admin@{get_settings().public_base_url}"},
    )


async def notify(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    kind: str,
    title: str,
    body: str = "",
    url: str | None = None,
) -> NotificationLog:
    entry = NotificationLog(user_id=user_id, kind=kind, title=title, body=body, url=url)
    db.add(entry)

    try:
        if user_id is None or not _vapid_ready():
            entry.status = "skipped"
            await db.flush()
            return entry

        subs = list(
            (await db.execute(select(PushSubscription).where(PushSubscription.user_id == user_id)))
            .scalars()
            .all()
        )
        if not subs:
            entry.status = "no_subs"
            await db.flush()
            return entry

        payload = {"title": title, "body": body, "url": url}
        sent = failed = 0
        for sub in subs:
            try:
                await asyncio.to_thread(_send_one, sub, payload)
                sent += 1
            except Exception as exc:
                failed += 1
                if getattr(getattr(exc, "response", None), "status_code", None) in (404, 410):
                    await db.delete(sub)
                entry.error = (entry.error or "") + f"{type(exc).__name__}: {exc}\n"
        entry.status = "sent" if sent else "failed"
    except Exception as exc:
        log.exception("notify failed")
        entry.status = "failed"
        entry.error = f"{type(exc).__name__}: {exc}"

    await db.flush()
    return entry


# --- event helpers ---------------------------------------------------------

_VERDICT_COPY = {
    "pass": ("All done! ✅", "Nice work — that one's approved."),
    "fail": ("Not quite yet", "Have a look at the note and try again."),
    "needs_review": ("Sent to a parent 👀", "A grown-up will check this one."),
    "retake": ("Retake the photo", "We couldn't see clearly — try again."),
    "error": ("Sent to a parent 👀", "We'll sort this one out for you."),
}


async def notify_verdict(
    db: AsyncSession, occ: ChoreOccurrence, verification: Verification | None
) -> None:
    if occ.assignee_id is None:
        return
    outcome = str(verification.verdict) if verification else "needs_review"
    title, body = _VERDICT_COPY.get(outcome, _VERDICT_COPY["needs_review"])
    if verification and verification.child_message:
        body = verification.child_message
    await notify(
        db,
        user_id=occ.assignee_id,
        kind=f"verdict.{outcome}",
        title=title,
        body=body,
        url=f"/me/chores/{occ.id}",
    )


async def notify_admins(
    db: AsyncSession, *, kind: str, title: str, body: str, url: str | None = None
) -> None:
    admins = list(
        (await db.execute(select(User).where(User.role == UserRole.admin))).scalars().all()
    )
    for admin in admins:
        await notify(db, user_id=admin.id, kind=kind, title=title, body=body, url=url)


async def notify_needs_review(db: AsyncSession, occ: ChoreOccurrence) -> None:
    chore = await db.get(Chore, occ.chore_id)
    await notify_admins(
        db,
        kind="admin.needs_review",
        title="A chore needs your review",
        body=chore.title if chore else "Open the review inbox",
        url=f"/admin/review/{occ.id}",
    )


async def notify_redo(db: AsyncSession, occ: ChoreOccurrence, note: str) -> None:
    if occ.assignee_id is None:
        return
    await notify(
        db,
        user_id=occ.assignee_id,
        kind="redo",
        title="Please redo this chore",
        body=note or "A parent asked you to try again.",
        url=f"/me/chores/{occ.id}",
    )


async def notify_dispute(db: AsyncSession, occ: ChoreOccurrence, message: str) -> None:
    await notify_admins(
        db,
        kind="admin.dispute",
        title="A dispute was filed",
        body=message[:140],
        url=f"/admin/review/{occ.id}",
    )


async def notify_dispute_resolved(db: AsyncSession, dispute, note: str) -> None:
    await notify(
        db,
        user_id=dispute.author_user_id,
        kind="dispute.resolved",
        title="A parent replied",
        body=note[:140],
        url=f"/me/chores/{dispute.occurrence_id}",
    )
