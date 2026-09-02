"""The one-off that opens the household's real books (app/prep_prod.py).

It deletes money, which nothing else in this codebase is allowed to do, so what it deletes
and what it writes back is worth pinning down.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.models import (
    Chore,
    ChoreOccurrence,
    LedgerEntry,
    LedgerKind,
    OccurrenceStatus,
    User,
    UserRole,
)
from app.prep_prod import prepare
from app.services.ledger import balance_cents

pytestmark = pytest.mark.asyncio

START = date(2026, 8, 31)  # a Monday
# Wednesday lunchtime in America/Los_Angeles — mid-window, and after the 08:00 due time, so
# a "today" row exists that is not yet due at the wall-clock hour the family would see.
NOW = datetime(2026, 9, 2, 19, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def kid(db_session, household) -> User:
    u = User(
        household_id=household.id,
        username="alice",
        display_name="Alice",
        role=UserRole.child,
    )
    db_session.add(u)
    await db_session.commit()
    return u


def _chore(household, kid, **over) -> Chore:
    base = {
        "household_id": household.id,
        "title": "Kitchen",
        "chore_kind": "scheduled",
        "cadence": "daily",
        "due_time": time(8, 0),
        "assignment_mode": "fixed",
        "proof_type": "acknowledgement",
        "verification_mode": "manual",
        "fixed_assignee_id": kid.id,
        "assignee_ids": [],
        "reward_cents": 500,
        "penalty_cents": 300,
        "start_date": date(2025, 1, 1),
        "active": True,
    }
    return Chore(**{**base, **over})


async def test_wipes_history_and_opens_the_books(db_session, household, kid):
    """The whole operation on a database that looks like the dev one did."""
    chore = _chore(household, kid)
    stale = _chore(household, kid, title="drum test", active=False)
    db_session.add_all([chore, stale])
    await db_session.flush()

    # Residue: an old occurrence well outside the window, and money owed against it.
    old = ChoreOccurrence(
        household_id=household.id,
        chore_id=chore.id,
        assignee_id=kid.id,
        window_open_at=datetime(2025, 6, 1, 7, tzinfo=UTC),
        due_at=datetime(2025, 6, 1, 8, tzinfo=UTC),
        status=OccurrenceStatus.missed,
        penalty_cents=300,
    )
    db_session.add(old)
    await db_session.flush()
    db_session.add(
        LedgerEntry(
            household_id=household.id,
            child_id=kid.id,
            occurrence_id=old.id,
            kind=LedgerKind.penalty,
            amount_cents=-300,
            reason="dev residue",
        )
    )
    await db_session.commit()

    report = await prepare(db_session, start=START, now=NOW)
    await db_session.commit()

    # The residue is gone — not reversed, deleted.
    assert report["wiped"] == {"ledger_entries": 1, "chore_occurrences": 1}
    assert report["dropped"] == ["drum test"]
    assert await db_session.scalar(select(func.count()).select_from(Chore)) == 1
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(ChoreOccurrence)
            .where(ChoreOccurrence.due_at < datetime(2026, 8, 31, tzinfo=UTC))
        )
        == 0
    )

    # The active chore starts on the opening day.
    assert (await db_session.get(Chore, chore.id)).start_date == START

    # Aug 31, Sep 1, Sep 2 — approved and paid at the chore's reward.
    assert report["backfill"]["approved"] == 3
    assert report["backfill"]["missed"] == 0
    assert await balance_cents(db_session, kid.id) == 1500

    earnings = (
        (
            await db_session.execute(
                select(LedgerEntry).where(LedgerEntry.kind == LedgerKind.earning)
            )
        )
        .scalars()
        .all()
    )
    assert len(earnings) == 3
    assert {e.reason for e in earnings} == {"opening balance: chore done"}
    # One entry per occurrence, and every one of them points at a row that still exists.
    assert len({e.occurrence_id for e in earnings}) == 3


async def test_miss_titles_land_missed_and_settled_without_pay(db_session, household, kid):
    """A chore in MISS_TITLES is history the family did not do — no reward, and settled, so
    the worker's settle scan has nothing left to charge."""
    db_session.add(_chore(household, kid, title="Walk the dog", reward_cents=200, penalty_cents=0))
    await db_session.commit()

    report = await prepare(db_session, start=START, now=NOW)
    await db_session.commit()

    assert report["backfill"]["approved"] == 0
    assert report["backfill"]["missed"] == 3
    rows = (
        (await db_session.execute(select(ChoreOccurrence).where(ChoreOccurrence.due_at <= NOW)))
        .scalars()
        .all()
    )
    assert [r.status for r in rows] == [OccurrenceStatus.missed] * 3
    assert all(r.settled_at is not None for r in rows)
    # Penalty is zero, so a miss costs nothing — the balance must not drift.
    assert await balance_cents(db_session, kid.id) == 0


async def test_a_missed_chore_that_does_cost_is_charged_once(db_session, household, kid):
    """MISS_TITLES on a chore with a real penalty still settles the money, exactly once."""
    db_session.add(_chore(household, kid, title="Walk the dog", penalty_cents=300))
    await db_session.commit()

    await prepare(db_session, start=START, now=NOW)
    await db_session.commit()

    assert await balance_cents(db_session, kid.id) == -900  # 3 days at -$3.00
    penalties = await db_session.scalar(
        select(func.count()).select_from(LedgerEntry).where(LedgerEntry.kind == LedgerKind.penalty)
    )
    assert penalties == 3


async def test_running_it_twice_does_not_double_pay(db_session, household, kid):
    """The wipe is what makes it idempotent: a second run rebuilds the same books rather
    than crediting a second opening balance on top of the first."""
    db_session.add(_chore(household, kid))
    await db_session.commit()

    await prepare(db_session, start=START, now=NOW)
    await db_session.commit()
    first = await balance_cents(db_session, kid.id)

    await prepare(db_session, start=START, now=NOW)
    await db_session.commit()

    assert await balance_cents(db_session, kid.id) == first == 1500
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(LedgerEntry)
            .where(LedgerEntry.kind == LedgerKind.earning)
        )
        == 3
    )


async def test_standing_and_penalty_rules_are_redated_but_not_materialised(
    db_session, household, kid
):
    """Only scheduled chores have occurrences (spec §4.7, §4.8) — the other two kinds must be
    re-dated and otherwise left alone, not backfilled into phantom history."""
    standing = _chore(
        household, kid, title="Missing assignments", chore_kind="standing", cadence="standing"
    )
    penalty = _chore(
        household, kid, title="Late to school", chore_kind="penalty", cadence="penalty"
    )
    db_session.add_all([standing, penalty])
    await db_session.commit()

    report = await prepare(db_session, start=START, now=NOW)
    await db_session.commit()

    assert report["redated"] == 2
    assert (await db_session.get(Chore, standing.id)).start_date == START
    assert (await db_session.get(Chore, penalty.id)).start_date == START
    assert await db_session.scalar(select(func.count()).select_from(ChoreOccurrence)) == 0


async def test_the_forward_horizon_is_generated_and_not_duplicated(db_session, household, kid):
    """Backfill covers up to today; the scheduler's own generation fills the days after, and
    must not collide with the rows just written for today."""
    db_session.add(_chore(household, kid))
    await db_session.commit()

    report = await prepare(db_session, start=START, now=NOW)
    await db_session.commit()

    assert report["generated"] > 0
    # Exactly one row per (chore, due_at) — the unique key held across both writers.
    dupes = (
        await db_session.execute(
            select(ChoreOccurrence.due_at, func.count())
            .group_by(ChoreOccurrence.due_at)
            .having(func.count() > 1)
        )
    ).all()
    assert dupes == []
