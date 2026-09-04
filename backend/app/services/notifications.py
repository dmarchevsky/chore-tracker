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
from datetime import UTC
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    Chore,
    ChoreOccurrence,
    Household,
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


async def notify_window_open(db: AsyncSession, occ: ChoreOccurrence) -> None:
    """Tell the kid a chore is now open to submit (spec §4.5).

    Sent from the same UPDATE that flips PENDING → OPEN, which happens exactly once per
    occurrence — so the transition is its own dedupe and no marker column is needed. An
    `anyone` occurrence has no assignee to tell.
    """
    if occ.assignee_id is None:
        return
    chore = await db.get(Chore, occ.chore_id)
    await notify(
        db,
        user_id=occ.assignee_id,
        kind="window_open",
        title="A chore just opened",
        body=f"{chore.title if chore else 'A chore'} — you can check it in now.",
        url=f"/me/chores/{occ.id}",
    )


async def notify_due_soon(db: AsyncSession, occ: ChoreOccurrence) -> None:
    """The T-30min nudge (spec §4.5). Times are shown in the household's wall clock."""
    if occ.assignee_id is None:
        return
    chore = await db.get(Chore, occ.chore_id)
    household = (await db.execute(select(Household).limit(1))).scalar_one_or_none()
    tz = ZoneInfo(household.timezone) if household else UTC
    when = occ.due_at.astimezone(tz).strftime("%-I:%M %p").lower()
    await notify(
        db,
        user_id=occ.assignee_id,
        kind="due_soon",
        title="Due soon",
        body=f"{chore.title if chore else 'A chore'} is due at {when}.",
        url=f"/me/chores/{occ.id}",
    )


async def notify_missed(db: AsyncSession, occ: ChoreOccurrence) -> None:
    """Tell the kid — and the parent — that a window closed (spec §6.2).

    Sent when the miss is detected, not when it is settled: the point is to reach them while
    there is still time to say it's wrong. An `anyone` occurrence has no assignee to tell,
    but the parent still hears about it.

    TODO(decision): spec §15 Q10 says misses reach the parent in the 8:05am digest rather
    than one push each. The household asked for them immediately and there is no digest job
    yet; revisit if the volume becomes noise.
    """
    chore = await db.get(Chore, occ.chore_id)
    title = chore.title if chore else "A chore"

    if occ.assignee_id is not None:
        cost = f" That costs you {occ.penalty_cents / 100:.2f}." if occ.penalty_cents else ""
        await notify(
            db,
            user_id=occ.assignee_id,
            kind="missed",
            title="You missed one",
            body=f"{title} closed without a check-in.{cost} Tell a parent if that's wrong.",
            url=f"/me/chores/{occ.id}",
        )

    kid = await db.get(User, occ.assignee_id) if occ.assignee_id else None
    await notify_admins(
        db,
        kind="admin.missed",
        title="A chore was missed",
        body=f"{kid.display_name} missed {title}." if kid else f"Nobody checked in {title}.",
        url=f"/admin/review/{occ.id}",
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


async def notify_penalty_applied(
    db: AsyncSession,
    chore: Chore,
    *,
    child_id: uuid.UUID,
    tier: dict | None,
    amount_cents: int,
    note: str | None,
) -> None:
    """Tell the kid a parent charged them against a penalty rule (spec §4.8).

    The kid, and only the kid: a sibling's money is not their business (spec §15 Q1), and the
    parent who applied it already knows. Says the condition and the cost in plain words — the
    rule was published in advance precisely so this is never a surprise. The url is ``/me``;
    the charge itself reads in full on the money screen.
    """
    cost = f"-{abs(amount_cents) / 100:.2f}"
    condition = (tier or {}).get("condition") or chore.title
    await notify(
        db,
        user_id=child_id,
        kind="penalty.applied",
        title=f"{chore.title}: {cost}"[:140],
        body=" — ".join(x for x in [condition, note] if x)[:140],
        url="/me",
    )
