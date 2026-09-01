"""Phase 8: a missed chore settles into the ledger on a delay, and can be appealed (spec §3, §9)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.config import get_settings
from app.models import (
    Chore,
    ChoreOccurrence,
    Dispute,
    DisputeStatus,
    LedgerEntry,
    LedgerKind,
    NotificationLog,
    OccurrenceStatus,
    User,
    UserRole,
)
from app.services import review
from app.services.ledger import balance_cents
from app.services.scheduler import detect_missed
from app.services.settlement import settle_missed

pytestmark = pytest.mark.asyncio

DUE = datetime(2025, 6, 1, 8, 0, tzinfo=UTC)
GRACE_S = 15 * 60
# Comfortably past due + grace + the settle delay.
AFTER = DUE + timedelta(seconds=GRACE_S + get_settings().miss_settle_delay_s + 60)


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


async def _missed(db, household, kid, *, penalty=500, status=OccurrenceStatus.missed):
    chore = Chore(
        household_id=household.id,
        title="Kitchen",
        assignment_mode="fixed",
        fixed_assignee_id=kid.id,
        cadence="daily",
        due_time=time(8, 0),
        grace_period_s=GRACE_S,
        start_date=date(2025, 1, 1),
        proof_type="photo",
        verification_mode="manual",
        reward_cents=200,
        penalty_cents=penalty,
    )
    db.add(chore)
    await db.flush()
    occ = ChoreOccurrence(
        household_id=household.id,
        chore_id=chore.id,
        assignee_id=kid.id,
        window_open_at=DUE - timedelta(hours=12),
        due_at=DUE,
        status=status,
        reward_cents=200,
        penalty_cents=penalty,
    )
    db.add(occ)
    await db.flush()
    return occ


async def _penalties(db) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(LedgerEntry)
            .where(LedgerEntry.kind == LedgerKind.penalty)
        )
    ).scalar_one()


async def test_nothing_is_charged_before_the_settle_delay(db_session, household, kid):
    occ = await _missed(db_session, household, kid)

    # The grace period has lapsed — the miss is real — but the delay has not.
    assert await settle_missed(db_session, now=DUE + timedelta(seconds=GRACE_S + 60)) == 0
    assert await _penalties(db_session) == 0
    assert occ.settled_at is None


async def test_the_penalty_lands_once_the_delay_has_elapsed(db_session, household, kid):
    occ = await _missed(db_session, household, kid)

    assert await settle_missed(db_session, now=AFTER) == 1
    assert await _penalties(db_session) == 1
    assert await balance_cents(db_session, kid.id) == -500
    assert occ.settled_at is not None


async def test_settling_twice_charges_once(db_session, household, kid):
    await _missed(db_session, household, kid)

    assert await settle_missed(db_session, now=AFTER) == 1
    assert await settle_missed(db_session, now=AFTER + timedelta(hours=1)) == 0
    assert await _penalties(db_session) == 1
    assert await balance_cents(db_session, kid.id) == -500


async def test_a_chore_with_no_penalty_is_settled_but_costs_nothing(db_session, household, kid):
    """Penalties are opt-in (spec §4.1) — but the row still has to leave the scan."""
    occ = await _missed(db_session, household, kid, penalty=0)

    assert await settle_missed(db_session, now=AFTER) == 1
    assert await _penalties(db_session) == 0
    assert occ.settled_at is not None
    assert await settle_missed(db_session, now=AFTER + timedelta(hours=1)) == 0


async def test_only_missed_occurrences_settle(db_session, household, kid):
    await _missed(db_session, household, kid, status=OccurrenceStatus.approved)

    assert await settle_missed(db_session, now=AFTER) == 0
    assert await _penalties(db_session) == 0


async def test_an_open_appeal_holds_the_money(db_session, household, kid):
    occ = await _missed(db_session, household, kid)
    d = Dispute(
        occurrence_id=occ.id,
        author_user_id=kid.id,
        message="I did do it",
        status_at_filing=str(occ.status),
    )
    db_session.add(d)
    await db_session.flush()

    assert await settle_missed(db_session, now=AFTER) == 0
    assert await _penalties(db_session) == 0

    # Resolving it without a decision lets the penalty stand.
    d.status = DisputeStatus.resolved
    await db_session.flush()
    assert await settle_missed(db_session, now=AFTER) == 1
    assert await balance_cents(db_session, kid.id) == -500


async def test_excusing_a_settled_miss_nets_the_balance_back_to_zero(
    db_session, household, kid, admin_user
):
    occ = await _missed(db_session, household, kid)
    await settle_missed(db_session, now=AFTER)
    assert await balance_cents(db_session, kid.id) == -500

    await review.apply_decision(
        db_session, occurrence=occ, admin=admin_user, action="excuse", reason="server was down"
    )
    await db_session.flush()

    assert await balance_cents(db_session, kid.id) == 0
    # Append-only: the penalty row stays, a reversing entry sits beside it (spec §9).
    assert await _penalties(db_session) == 1
    total = (await db_session.execute(select(func.count()).select_from(LedgerEntry))).scalar_one()
    assert total == 2


async def test_the_kid_is_told_at_detection_not_at_settlement(db_session, household, kid):
    """The push goes out while there is still time to appeal; the money follows later."""
    occ = await _missed(db_session, household, kid, status=OccurrenceStatus.open)

    assert await detect_missed(db_session, now=DUE + timedelta(seconds=GRACE_S + 60)) == 1
    logs = (await db_session.execute(select(NotificationLog))).scalars().all()
    assert [log.kind for log in logs] == ["missed"]
    assert logs[0].user_id == kid.id
    assert "Kitchen" in logs[0].body and "5.00" in logs[0].body
    # Told, but not yet charged.
    assert await _penalties(db_session) == 0
    assert occ.settled_at is None
