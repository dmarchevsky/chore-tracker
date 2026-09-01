"""Occurrence generation + state reconciliation (spec §8).

Everything here is **stateless reconciliation from the DB** — no in-memory timers. A tick
computes the desired set of occurrences for a rolling horizon and upserts it; two set-based
UPDATEs move rows OPEN when their window opens and MISSED once the grace period lapses.
A machine that was asleep for hours catches up correctly on the next tick (spec §8.3).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, literal, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chore, ChoreOccurrence, Household, OccurrenceStatus
from app.models.chore import AssignmentMode, ChoreKind
from app.services import notifications
from app.services.cadence import due_datetimes
from app.services.rotation import rotation_pick
from app.services.settlement import settle_missed

log = logging.getLogger("chorekeeper.scheduler")

DEFAULT_HORIZON_DAYS = 14
_PRE_MISSED = (OccurrenceStatus.pending, OccurrenceStatus.open)


@dataclass
class ReconcileReport:
    generated: int = 0
    opened: int = 0
    missed: int = 0
    settled: int = 0


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def _grace_interval():
    # make_interval(years, months, weeks, days, hours, mins, secs) — secs is the 7th arg.
    return func.make_interval(0, 0, 0, 0, 0, 0, Chore.grace_period_s)


def resolve_assignees(chore: Chore, due: date) -> list[object | None]:
    """Ordered assignee id(s) for ``due`` — one occurrence is created per element."""
    mode = AssignmentMode(chore.assignment_mode)
    if mode is AssignmentMode.fixed:
        return [chore.fixed_assignee_id]
    if mode is AssignmentMode.all:
        return list(chore.assignee_ids)
    if mode is AssignmentMode.anyone:
        return [None]  # claimed on completion
    if not chore.assignee_ids or not chore.rotation_anchor_date or not chore.rotation_period:
        raise ValueError(f"chore {chore.id} is rotating but misconfigured")
    return [
        rotation_pick(chore.assignee_ids, chore.rotation_anchor_date, due, chore.rotation_period)
    ]


def _initial_status(window_open_at: datetime, due_at: datetime, grace_s: int, now: datetime) -> str:
    if now > due_at + timedelta(seconds=grace_s):
        return OccurrenceStatus.missed
    if now >= window_open_at:
        return OccurrenceStatus.open
    return OccurrenceStatus.pending


async def generate_occurrences(
    db: AsyncSession,
    *,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    now: datetime | None = None,
) -> int:
    """Materialise every active chore's occurrences for ``[today, today+horizon]``.

    Idempotent: rows are upserted with ``ON CONFLICT DO NOTHING`` against the
    ``(chore_id, due_at, assignee_id)`` key and the NULL-assignee partial index (spec §8.1).
    Returns the number of rows actually inserted.
    """
    now = _now(now)
    household = (await db.execute(select(Household).limit(1))).scalar_one()
    tz = ZoneInfo(household.timezone)
    today = now.astimezone(tz).date()
    horizon_end = today + timedelta(days=horizon_days)

    chores = (
        (
            await db.execute(
                select(Chore).where(Chore.active.is_(True), Chore.chore_kind == ChoreKind.scheduled)
            )
        )
        .scalars()
        .all()
    )

    rows: list[dict] = []
    for chore in chores:
        win_start = max(chore.start_date, today)
        win_end = horizon_end if chore.end_date is None else min(chore.end_date, horizon_end)
        for due_at in due_datetimes(chore.cadence, win_start, win_end, chore.due_time, tz):
            window_open_at = due_at + timedelta(seconds=chore.window_open_offset_s)
            status = _initial_status(window_open_at, due_at, chore.grace_period_s, now)
            for assignee_id in resolve_assignees(chore, due_at.astimezone(tz).date()):
                rows.append(
                    {
                        "household_id": household.id,
                        "chore_id": chore.id,
                        "assignee_id": assignee_id,
                        "window_open_at": window_open_at,
                        "due_at": due_at,
                        "status": status,
                        "was_late": False,
                        "outcome_tiers": chore.outcome_tiers,
                        "reward_cents": chore.reward_cents,
                        "penalty_cents": chore.penalty_cents,
                        "late_multiplier": chore.late_multiplier,
                    }
                )

    if not rows:
        return 0

    result = await db.execute(pg_insert(ChoreOccurrence).values(rows).on_conflict_do_nothing())
    await db.flush()
    return result.rowcount or 0


async def open_due_windows(db: AsyncSession, *, now: datetime | None = None) -> int:
    """PENDING → OPEN once the window has opened and grace has not yet lapsed (spec §3)."""
    now = _now(now)
    ts = literal(now)
    result = await db.execute(
        update(ChoreOccurrence)
        .where(
            ChoreOccurrence.status == OccurrenceStatus.pending,
            ChoreOccurrence.chore_id == Chore.id,
            Chore.chore_kind == ChoreKind.scheduled,
            ChoreOccurrence.window_open_at <= ts,
            ts <= ChoreOccurrence.due_at + _grace_interval(),
        )
        .values(status=OccurrenceStatus.open)
        .execution_options(synchronize_session=False)
    )
    await db.flush()
    return result.rowcount or 0


async def detect_missed(db: AsyncSession, *, now: datetime | None = None) -> int:
    """PENDING/OPEN → MISSED where ``now > due_at + grace`` (spec §8.3).

    Set by the scheduler, never by a user action — a query over state, so a long outage
    is caught up on the next tick. The kid is told now, when there is still time to appeal;
    the money follows later, in ``settlement.settle_missed``.
    """
    now = _now(now)
    ts = literal(now)
    result = await db.execute(
        update(ChoreOccurrence)
        .where(
            ChoreOccurrence.status.in_(_PRE_MISSED),
            ChoreOccurrence.chore_id == Chore.id,
            Chore.chore_kind == ChoreKind.scheduled,
            ts > ChoreOccurrence.due_at + _grace_interval(),
        )
        .values(status=OccurrenceStatus.missed)
        .returning(ChoreOccurrence.id)
        .execution_options(synchronize_session=False)
    )
    ids = list(result.scalars().all())
    await db.flush()
    for occ in (
        await db.execute(select(ChoreOccurrence).where(ChoreOccurrence.id.in_(ids)))
    ).scalars():
        await notifications.notify_missed(db, occ)
    return len(ids)


async def reconcile(
    db: AsyncSession,
    *,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    now: datetime | None = None,
) -> ReconcileReport:
    """One full pass: generate, open windows, detect missed, settle the ones now due
    (spec §8.3). Logs a summary."""
    now = _now(now)
    report = ReconcileReport(
        generated=await generate_occurrences(db, horizon_days=horizon_days, now=now),
        opened=await open_due_windows(db, now=now),
        missed=await detect_missed(db, now=now),
        settled=await settle_missed(db, now=now),
    )
    log.info(
        "reconcile: generated=%d opened=%d missed=%d settled=%d",
        report.generated,
        report.opened,
        report.missed,
        report.settled,
    )
    return report
