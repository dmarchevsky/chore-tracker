"""Settling missed chores into the money ledger (spec §3, §9).

``detect_missed`` flags a miss the moment the grace period lapses; the money moves here, a
configurable delay later. The gap is deliberate: this is a home server, and a machine that
was down for a few hours catches up in a single pass (spec §8.3) — debiting immediately
would charge a pile of false penalties that a parent then has to reverse one by one
(spec §16). The delay is the window in which the parent can excuse them, or the kid can
appeal, before anything is charged.

Like everything else in the scheduler, this is reconciliation from the DB rather than a
timer: settling is a query over state, safe to run on every tick and after any outage.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Chore, ChoreOccurrence, Dispute, DisputeStatus, OccurrenceStatus
from app.models.chore import ChoreKind
from app.services import audit, ledger

log = logging.getLogger("chorekeeper.scheduler")


def _due_for_settlement(now: datetime):
    """MISSED, unsettled, past ``due_at + grace + settle delay``, and not under appeal."""
    ts = literal(now)
    grace = func.make_interval(0, 0, 0, 0, 0, 0, Chore.grace_period_s)
    delay = func.make_interval(0, 0, 0, 0, 0, 0, literal(get_settings().miss_settle_delay_s))
    open_appeal = (
        select(Dispute.id)
        .where(
            Dispute.occurrence_id == ChoreOccurrence.id,
            Dispute.status == DisputeStatus.open,
        )
        .exists()
    )
    return (
        select(ChoreOccurrence)
        .join(Chore, Chore.id == ChoreOccurrence.chore_id)
        .where(
            ChoreOccurrence.status == OccurrenceStatus.missed,
            ChoreOccurrence.settled_at.is_(None),
            Chore.chore_kind == ChoreKind.scheduled,
            ts >= ChoreOccurrence.due_at + grace + delay,
            # An open appeal holds the money where it is until a parent has answered it.
            ~open_appeal,
        )
        .order_by(ChoreOccurrence.due_at)
    )


async def settle_missed(db: AsyncSession, *, now: datetime | None = None) -> int:
    """Post the penalty for every miss whose settle delay has elapsed. Returns the count.

    The status stays MISSED — the consequence lives in the ledger, not in the state machine,
    and an admin can still approve/excuse the occurrence afterwards, which writes the
    reversing entry (spec §3, §9). Rows with no penalty are stamped settled anyway so the
    scan does not keep revisiting them.
    """
    now = now or datetime.now(UTC)
    rows = list((await db.execute(_due_for_settlement(now))).scalars().all())
    for occ in rows:
        entry = await ledger.debit_penalty(db, occurrence=occ, actor=None, reason="chore missed")
        occ.settled_at = now
        await audit.record(
            db,
            action="occurrence.settle_missed",
            entity_type="occurrence",
            entity_id=occ.id,
            actor_kind="system",
            after={
                "penalty_cents": occ.penalty_cents,
                "ledger_entry_id": str(entry.id) if entry else None,
            },
        )
    await db.flush()
    if rows:
        log.info("settle_missed: settled=%d", len(rows))
    return len(rows)
