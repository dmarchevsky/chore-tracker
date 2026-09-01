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
from collections.abc import Sequence

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


async def notify_missed(db: AsyncSession, occ: ChoreOccurrence) -> None:
    """Tell the kid a window closed on them (spec §6.2).

    Sent when the miss is detected, not when it is settled: the point is to reach them while
    there is still time to say it's wrong. The parent hears about misses in the daily digest
    instead of one push per miss (spec §15 Q10). An `anyone` occurrence has no assignee to
    tell.
    """
    if occ.assignee_id is None:
        return
    chore = await db.get(Chore, occ.chore_id)
    cost = f" That costs you {occ.penalty_cents / 100:.2f}." if occ.penalty_cents else ""
    await notify(
        db,
        user_id=occ.assignee_id,
        kind="missed",
        title="You missed one",
        body=f"{chore.title if chore else 'A chore'} closed without a check-in.{cost}"
        " Tell a parent if that's wrong.",
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


async def notify_standing_flip(
    db: AsyncSession,
    chore: Chore,
    *,
    on: bool,
    tier: dict | None,
    note: str | None,
    recipients: Sequence[uuid.UUID],
) -> None:
    """Tell the kid a standing rule started or ended (spec §4.7).

    A standing chore has no occurrence, so the flip *is* the event. Assignees only: whether a
    rule is in force is the assignee's own business (spec §15 Q1), and the parent who flipped
    it already knows.

    ``tier`` is a raw JSONB snapshot rather than a validated model, hence the fallbacks. The
    url is ``/me`` because there is no standing detail route — that is where StandingBanner
    renders, so the link lands on the thing the notification is about.
    """
    if on:
        title = ((tier or {}).get("text") or chore.title)[:140]
        body = " — ".join(x for x in [(tier or {}).get("condition"), note] if x)[:140]
    else:
        title = "That's lifted"
        body = chore.title[:140]

    for user_id in recipients:
        await notify(
            db,
            user_id=user_id,
            kind=f"standing.{'on' if on else 'off'}",
            title=title,
            body=body,
            url="/me",
        )
