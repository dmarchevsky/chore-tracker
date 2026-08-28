"""Phase 3: ledger exactly-once index + submission media constraints (spec §9, §7.1)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import (
    Chore,
    ChoreOccurrence,
    LedgerEntry,
    OccurrenceStatus,
    Submission,
    SubmissionMedia,
)

pytestmark = pytest.mark.asyncio


async def _occurrence(db, household, child) -> ChoreOccurrence:
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
        reward_cents=200,
    )
    db.add(chore)
    await db.flush()
    occ = ChoreOccurrence(
        household_id=household.id,
        chore_id=chore.id,
        assignee_id=child.id,
        window_open_at=datetime(2025, 1, 2, 4, tzinfo=UTC),
        due_at=datetime(2025, 1, 2, 16, tzinfo=UTC),
        status=OccurrenceStatus.open,
        reward_cents=200,
    )
    db.add(occ)
    await db.flush()
    return occ


async def test_earning_is_exactly_once_per_occurrence(db_session, household, child_user):
    occ = await _occurrence(db_session, household, child_user)

    def _earn():
        return LedgerEntry(
            household_id=household.id,
            child_id=child_user.id,
            occurrence_id=occ.id,
            kind="earning",
            amount_cents=200,
            reason="approved",
        )

    db_session.add(_earn())
    await db_session.commit()

    db_session.add(_earn())
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_adjustments_and_payouts_are_unrestricted(db_session, household, child_user):
    occ = await _occurrence(db_session, household, child_user)
    for _ in range(3):
        db_session.add(
            LedgerEntry(
                household_id=household.id,
                child_id=child_user.id,
                occurrence_id=occ.id,
                kind="adjustment",
                amount_cents=-50,
                reason="fix",
            )
        )
    db_session.add(
        LedgerEntry(
            household_id=household.id,
            child_id=child_user.id,
            kind="payout",
            amount_cents=-500,
            reason="cash",
            meta={"method": "cash"},
        )
    )
    await db_session.commit()  # no error


async def test_submission_media_idx_unique(db_session, household, child_user):
    occ = await _occurrence(db_session, household, child_user)
    sub = Submission(occurrence_id=occ.id, submitter_id=child_user.id, kind="photo")
    db_session.add(sub)
    await db_session.flush()

    def _media():
        return SubmissionMedia(
            submission_id=sub.id,
            idx=0,
            sha256="a" * 64,
            width=100,
            height=100,
            bytes=123,
            storage_path="x/y.jpg",
        )

    db_session.add(_media())
    await db_session.commit()
    db_session.add(_media())
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
