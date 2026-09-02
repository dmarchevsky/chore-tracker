"""Scheduler liveness (implementation-plan Phase 6 items 6, 8).

The worker is where chores get generated, windows open, misses are detected and money is
settled. When it stops, none of that happens and nothing anywhere says so — the app keeps
serving yesterday's occurrences and looks entirely healthy. So every completed pass stamps
a timestamp the admin Ops screen reads back.

Kept out of `worker/scheduler.py` so the API can read it without importing the worker.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Household, HouseholdSettings

# The loop ticks every 60s. Three missed ticks is a real stop, not a slow pass — short
# enough that a parent finds out the same morning, long enough not to cry wolf on a restart.
STALE_AFTER_S = 300


async def record_tick(db: AsyncSession, *, now: datetime | None = None) -> None:
    """Stamp a completed scheduler pass. Silently does nothing before the household exists
    — an empty database is a normal state on a fresh volume, not a fault."""
    row = (await db.execute(select(HouseholdSettings).limit(1))).scalar_one_or_none()
    if row is None:
        household_id = (await db.execute(select(Household.id).limit(1))).scalar_one_or_none()
        if household_id is None:
            return
        row = HouseholdSettings(household_id=household_id)
        db.add(row)
    row.last_scheduler_tick_at = now or datetime.now(UTC)


async def last_tick(db: AsyncSession) -> datetime | None:
    row = (await db.execute(select(HouseholdSettings).limit(1))).scalar_one_or_none()
    return row.last_scheduler_tick_at if row is not None else None


def is_stale(at: datetime | None, *, now: datetime | None = None) -> bool:
    """True when the scheduler has not ticked recently — including when it never has."""
    if at is None:
        return True
    return (now or datetime.now(UTC)) - at > timedelta(seconds=STALE_AFTER_S)
