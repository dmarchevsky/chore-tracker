"""Phase 2: occurrence generation, rotation, idempotency, missed/open transitions (§8)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest_asyncio
from sqlalchemy import delete, func, select

from app.models import Chore, ChoreOccurrence, Household, OccurrenceStatus, User, UserRole
from app.services.scheduler import (
    detect_missed,
    generate_occurrences,
    open_due_windows,
    reconcile,
)

NOW = datetime(2025, 6, 1, 12, 0, tzinfo=UTC)  # 05:00 America/Los_Angeles


async def _count(db, **where) -> int:
    stmt = select(func.count()).select_from(ChoreOccurrence)
    for k, v in where.items():
        stmt = stmt.where(getattr(ChoreOccurrence, k) == v)
    return (await db.execute(stmt)).scalar_one()


@pytest_asyncio.fixture
async def kids(db_session, household) -> tuple[User, User]:
    a = User(
        household_id=household.id,
        username="alice",
        display_name="Alice",
        role=UserRole.child,
    )
    b = User(
        household_id=household.id,
        username="bea",
        display_name="Bea",
        role=UserRole.child,
    )
    db_session.add_all([a, b])
    await db_session.commit()
    return a, b


def _chore(household, **over) -> Chore:
    base = {
        "household_id": household.id,
        "title": "Kitchen",
        "assignment_mode": "anyone",
        "cadence": "daily",
        "due_time": time(8, 0),
        "window_open_offset_s": -12 * 3600,
        "grace_period_s": 15 * 60,
        "start_date": date(2025, 1, 1),
        "proof_type": "photo",
        "verification_mode": "manual",
        "reward_cents": 200,
    }
    base.update(over)
    return Chore(**base)


async def test_daily_horizon_is_inclusive_both_ends(db_session, household):
    db_session.add(_chore(household))
    await db_session.commit()

    inserted = await generate_occurrences(db_session, horizon_days=14, now=NOW)
    await db_session.commit()

    # 2025-06-01 .. 2025-06-15 inclusive = 15 days.
    assert inserted == 15
    assert await _count(db_session) == 15


async def test_generation_is_idempotent(db_session, household):
    db_session.add(_chore(household))
    await db_session.commit()

    first = await generate_occurrences(db_session, horizon_days=14, now=NOW)
    await db_session.commit()
    second = await generate_occurrences(db_session, horizon_days=14, now=NOW)
    await db_session.commit()

    assert first == 15
    assert second == 0
    assert await _count(db_session) == 15


async def test_all_mode_one_occurrence_per_kid(db_session, household, kids):
    a, b = kids
    db_session.add(_chore(household, assignment_mode="all", assignee_ids=[a.id, b.id]))
    await db_session.commit()

    await generate_occurrences(db_session, horizon_days=6, now=NOW)
    await db_session.commit()

    assert await _count(db_session) == 2 * 7  # 2025-06-01..06-07
    assert await _count(db_session, assignee_id=a.id) == 7
    assert await _count(db_session, assignee_id=b.id) == 7


async def test_biweekly_rotation_is_alice_alice_bea_bea(db_session, household, kids):
    a, b = kids
    db_session.add(
        _chore(
            household,
            assignment_mode="rotating",
            cadence="weekly(on=[MON])",
            assignee_ids=[a.id, b.id],
            rotation_period="biweekly",
            rotation_anchor_date=date(2025, 6, 2),  # first Monday in range
        )
    )
    await db_session.commit()

    await generate_occurrences(db_session, horizon_days=28, now=NOW)
    await db_session.commit()

    rows = (
        (await db_session.execute(select(ChoreOccurrence).order_by(ChoreOccurrence.due_at)))
        .scalars()
        .all()
    )
    assert [r.due_at.astimezone(UTC).date() for r in rows] == [
        date(2025, 6, 2),
        date(2025, 6, 9),
        date(2025, 6, 16),
        date(2025, 6, 23),
    ]
    assert [r.assignee_id for r in rows] == [a.id, a.id, b.id, b.id]


async def test_snapshots_money_and_window(db_session, household):
    db_session.add(
        _chore(household, reward_cents=250, penalty_cents=50, window_open_offset_s=-3600)
    )
    await db_session.commit()
    await generate_occurrences(db_session, horizon_days=1, now=NOW)
    await db_session.commit()

    occ = (await db_session.execute(select(ChoreOccurrence).limit(1))).scalar_one()
    assert occ.reward_cents == 250 and occ.penalty_cents == 50
    assert (occ.due_at - occ.window_open_at) == timedelta(hours=1)


async def test_end_date_caps_generation(db_session, household):
    db_session.add(_chore(household, end_date=date(2025, 6, 3)))
    await db_session.commit()
    await generate_occurrences(db_session, horizon_days=14, now=NOW)
    await db_session.commit()
    assert await _count(db_session) == 3  # 06-01, 06-02, 06-03


async def test_detect_missed_flips_only_past_grace(db_session, household):
    db_session.add(_chore(household))
    await db_session.commit()
    await generate_occurrences(db_session, horizon_days=14, now=NOW)
    await db_session.commit()

    # 2025-06-02 16:00Z: 06-01 (due 15:00Z) and 06-02 (due 15:00Z) are past due+grace;
    # 06-03 (due 2025-06-03 15:00Z) is not.
    later = NOW + timedelta(days=1, hours=4)
    flipped = await detect_missed(db_session, now=later)
    await db_session.commit()

    assert flipped == 2
    assert await _count(db_session, status=OccurrenceStatus.missed) == 2


async def test_open_due_windows_activates_pending(db_session, household):
    # 1h window: for an 08:00-local (15:00Z) due time the window opens at 14:00Z.
    db_session.add(_chore(household, window_open_offset_s=-3600))
    await db_session.commit()
    await generate_occurrences(db_session, horizon_days=14, now=NOW)  # NOW = 12:00Z
    await db_session.commit()
    assert await _count(db_session, status=OccurrenceStatus.pending) == 15

    # 14:30Z on 2025-06-01 -> first window is open, the rest are still pending.
    mid_window = datetime(2025, 6, 1, 14, 30, tzinfo=UTC)
    opened = await open_due_windows(db_session, now=mid_window)
    await db_session.commit()
    assert opened == 1
    assert await _count(db_session, status=OccurrenceStatus.open) == 1


async def test_reconcile_catches_up_after_a_short_sleep(db_session, household):
    db_session.add(_chore(household))
    await db_session.commit()
    await generate_occurrences(db_session, horizon_days=14, now=NOW)  # occurrences exist
    await db_session.commit()

    # Machine napped ~2 days; the first tick after waking must flip every lapsed row.
    wake = NOW + timedelta(days=2, hours=6)  # 2025-06-03 18:00Z
    report = await reconcile(db_session, horizon_days=14, now=wake)
    await db_session.commit()

    # 06-01, 06-02, 06-03 all past due+grace; 06-04 (due 06-04 15:00Z) is not.
    assert report.missed == 3
    assert await _count(db_session, status=OccurrenceStatus.missed) == 3


async def test_one_off_generates_exactly_one_occurrence_across_repeated_ticks(
    db_session, household, kids
):
    """The reason once() carries its own date: cadence_dates only ever sees the scheduler's
    clamped window, so a date-less token would fire on every tick forever."""
    on = (NOW + timedelta(days=3)).date()
    db_session.add(_chore(household, cadence=f"once({on.isoformat()})"))
    await db_session.flush()

    await generate_occurrences(db_session, now=NOW)
    await generate_occurrences(db_session, now=NOW + timedelta(days=1))
    await generate_occurrences(db_session, now=NOW + timedelta(days=2))

    assert await _count(db_session) == 1


async def test_one_off_stops_generating_once_its_date_has_passed(db_session, household, kids):
    on = (NOW + timedelta(days=2)).date()
    db_session.add(_chore(household, cadence=f"once({on.isoformat()})"))
    await db_session.flush()

    await generate_occurrences(db_session, now=NOW)
    assert await _count(db_session) == 1

    # Wipe it and tick again from a day after the date — nothing comes back.
    await db_session.execute(delete(ChoreOccurrence))
    await generate_occurrences(db_session, now=NOW + timedelta(days=3))
    assert await _count(db_session) == 0


async def test_one_off_goes_missed_after_its_grace_period(db_session, household, kids):
    """A one-off is an ordinary occurrence once materialised — nothing special downstream."""
    on = NOW.date()
    db_session.add(_chore(household, cadence=f"once({on.isoformat()})"))
    await db_session.flush()

    # due 08:00 local on the day; NOW is 05:00 local, so it starts open, then lapses.
    await reconcile(db_session, now=NOW)
    assert await _count(db_session, status=OccurrenceStatus.open) == 1

    await detect_missed(db_session, now=NOW + timedelta(days=1))
    assert await _count(db_session, status=OccurrenceStatus.missed) == 1


async def test_generate_is_a_quiet_no_op_before_the_household_exists(db_session):
    """A production stack comes up on an empty volume and stays empty until the bootstrap
    seed runs. Raising there turned every worker tick into a traceback, which is how a real
    fault gets lost in the noise (docs/deploy-dockhand.md, readiness item 11)."""
    await db_session.execute(delete(Household))
    await db_session.commit()

    assert await generate_occurrences(db_session, now=NOW) == 0
    report = await reconcile(db_session, now=NOW)
    assert (report.generated, report.opened, report.missed) == (0, 0, 0)
