"""Turning a standing chore on and off (spec §4.7).

A standing chore has no occurrences and no ledger entries — flipping it *is* the whole
lifecycle, so every flip is recorded with its actor, timestamp and a snapshot of the
outcome that was put in force.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chore, ChoreKind, ChoreStateEvent, User
from app.services import audit, notifications
from app.services.scheduler import resolve_assignees


class StandingError(ValueError):
    """Raised for a flip that doesn't apply to this chore."""


async def set_state(
    db: AsyncSession,
    *,
    chore: Chore,
    actor: User | None,
    on: bool,
    tier_id: int | None = None,
    note: str | None = None,
    now: datetime | None = None,
) -> ChoreStateEvent:
    # chore_kind is a plain String column, so a row loaded in a later request carries a str,
    # not the enum member — `is not` would silently match nothing (same trap as review.py).
    if chore.chore_kind != ChoreKind.standing:
        raise StandingError("only a standing chore has a state to flip")

    tiers = chore.outcome_tiers or []
    tier = None
    if on:
        if tier_id is None:
            raise StandingError("turning a standing chore on needs the outcome that applies")
        tier = next((t for t in tiers if t["id"] == tier_id), None)
        if tier is None:
            raise StandingError(f"tier {tier_id} is not one of this chore's outcomes")
    elif tier_id is not None:
        raise StandingError("turning a standing chore off takes no tier")

    # Idempotent, like the tier decision: flipping to the state it is already in writes
    # nothing, so a double-tapped toggle doesn't litter the kid's history.
    if chore.standing_on == on and chore.standing_tier_id == tier_id:
        latest = await latest_event(db, chore.id)
        if latest is not None:
            return latest

    now = now or datetime.now(UTC)
    # Captured before the mutation: the short-circuit above only returns early once the chore
    # has a flip history, so a never-flipped chore told on=False still lands here and must not
    # send a "that's lifted" for something that was never in force.
    was_on = chore.standing_on
    chore.standing_on = on
    chore.standing_tier_id = tier_id
    chore.standing_since = now if on else None

    event = ChoreStateEvent(
        household_id=chore.household_id,
        chore_id=chore.id,
        actor_user_id=actor.id if actor else None,
        state=on,
        tier_id=tier_id,
        tier=tier,
        note=note,
    )
    db.add(event)
    await db.flush()

    await audit.record(
        db,
        actor=actor,
        action=f"chore.standing.{'on' if on else 'off'}",
        entity_type="chore",
        entity_id=chore.id,
        after={"on": on, "tier_id": tier_id, "note": note},
    )

    if on or was_on:
        # resolve_assignees ignores the date for fixed/all, the only two modes a standing
        # chore may use (_check_standing) — it is passed for documentation, not as an input.
        # It can yield None for a fixed chore with no assignee, which notify() would log as a
        # junk row.
        recipients = [uid for uid in resolve_assignees(chore, now.date()) if uid is not None]
        await notifications.notify_standing_flip(
            db, chore, on=on, tier=tier, note=note, recipients=recipients
        )
    return event


async def latest_event(db: AsyncSession, chore_id) -> ChoreStateEvent | None:
    return (
        await db.execute(
            select(ChoreStateEvent)
            .where(ChoreStateEvent.chore_id == chore_id)
            .order_by(desc(ChoreStateEvent.created_at), desc(ChoreStateEvent.id))
            .limit(1)
        )
    ).scalar_one_or_none()


async def history(db: AsyncSession, chore_id, *, limit: int = 50) -> list[ChoreStateEvent]:
    return list(
        (
            await db.execute(
                select(ChoreStateEvent)
                .where(ChoreStateEvent.chore_id == chore_id)
                .order_by(desc(ChoreStateEvent.created_at), desc(ChoreStateEvent.id))
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
