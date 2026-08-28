"""Phase 3: ledger operations — exactly-once, late multiplier, reversal, payout (spec §9)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

import pytest
from sqlalchemy import func, select

from app.models import Chore, ChoreOccurrence, LedgerEntry, LedgerKind, OccurrenceStatus
from app.services.ledger import (
    balance_cents,
    credit_earning,
    debit_penalty,
    record_payout,
    reverse_entry,
)

pytestmark = pytest.mark.asyncio


async def _occ(
    db,
    household,
    child,
    *,
    reward=200,
    penalty=0,
    was_late=False,
    mult=1.0,
    due=datetime(2025, 1, 2, 16, tzinfo=UTC),
) -> ChoreOccurrence:
    chore = Chore(
        household_id=household.id,
        title="Kitchen",
        assignment_mode="fixed",
        fixed_assignee_id=child.id,
        cadence="daily",
        due_time=time(8, 0),
        start_date=date(2025, 1, 1),
        proof_type="photo",
        verification_mode="manual",
        reward_cents=reward,
        penalty_cents=penalty,
    )
    db.add(chore)
    await db.flush()
    occ = ChoreOccurrence(
        household_id=household.id,
        chore_id=chore.id,
        assignee_id=child.id,
        window_open_at=due,
        due_at=due,
        status=OccurrenceStatus.open,
        reward_cents=reward,
        penalty_cents=penalty,
        was_late=was_late,
        late_multiplier=mult,
    )
    db.add(occ)
    await db.flush()
    return occ


async def _count(db) -> int:
    return (await db.execute(select(func.count()).select_from(LedgerEntry))).scalar_one()


async def test_credit_earning_is_exactly_once(db_session, household, child_user):
    occ = await _occ(db_session, household, child_user, reward=250)

    e1 = await credit_earning(db_session, occurrence=occ)
    e2 = await credit_earning(db_session, occurrence=occ)  # double-clicked approve
    await db_session.commit()

    assert e1.id == e2.id
    assert await _count(db_session) == 1
    assert await balance_cents(db_session, child_user.id) == 250


async def test_amount_override_wins_over_reward(db_session, household, child_user):
    occ = await _occ(db_session, household, child_user, reward=250)
    e = await credit_earning(
        db_session, occurrence=occ, amount_override_cents=100, reason="partial"
    )
    await db_session.commit()
    assert e.amount_cents == 100


async def test_late_multiplier_reduces_earning(db_session, household, child_user):
    occ = await _occ(db_session, household, child_user, reward=200, was_late=True, mult=0.5)
    e = await credit_earning(db_session, occurrence=occ)
    await db_session.commit()
    assert e.amount_cents == 100


async def test_penalty_opt_in(db_session, household, child_user):
    no_pen = await _occ(db_session, household, child_user, penalty=0)
    assert await debit_penalty(db_session, occurrence=no_pen) is None

    with_pen = await _occ(
        db_session, household, child_user, penalty=150, due=datetime(2025, 1, 3, 16, tzinfo=UTC)
    )
    e = await debit_penalty(db_session, occurrence=with_pen)
    dup = await debit_penalty(db_session, occurrence=with_pen)
    await db_session.commit()
    assert e.amount_cents == -150 and e.id == dup.id
    assert await balance_cents(db_session, child_user.id) == -150


async def test_reverse_entry_nets_to_zero_and_keeps_history(db_session, household, child_user):
    occ = await _occ(db_session, household, child_user, reward=300)
    earning = await credit_earning(db_session, occurrence=occ)
    comp = await reverse_entry(db_session, entry=earning, actor=None, reason="approved in error")
    await db_session.commit()

    assert comp.kind == LedgerKind.adjustment and comp.amount_cents == -300
    await db_session.refresh(earning)
    assert earning.reversed_by_entry_id == comp.id
    assert await _count(db_session) == 2  # nothing deleted
    assert await balance_cents(db_session, child_user.id) == 0


async def test_record_payout_locks_settlement(db_session, household, child_user):
    occ = await _occ(db_session, household, child_user, reward=500)
    await credit_earning(db_session, occurrence=occ)
    await db_session.commit()

    payout = await record_payout(
        db_session,
        child_id=child_user.id,
        household_id=household.id,
        amount_cents=500,
        method="cash",
        note="weekly",
        actor=None,
        covers_through=date(2025, 1, 31),
    )
    await db_session.commit()

    assert payout.kind == LedgerKind.payout and payout.amount_cents == -500
    assert payout.meta["method"] == "cash"
    assert await balance_cents(db_session, child_user.id) == 0

    await db_session.refresh(occ)
    assert occ.settlement_locked_at is not None
