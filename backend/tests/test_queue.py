"""Phase 4: Postgres verification job queue (spec §7.1, §8.3)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import (
    Chore,
    ChoreOccurrence,
    JobState,
    OccurrenceStatus,
    Submission,
    VerificationJob,
)
from app.worker import queue

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def occ_and_sub(db_session, household, child_user):
    chore = Chore(
        household_id=household.id,
        title="Kitchen",
        assignment_mode="fixed",
        fixed_assignee_id=child_user.id,
        cadence="daily",
        due_time=time(8, 0),
        start_date=date(2025, 1, 1),
        proof_type="photo",
        verification_mode="llm_auto",
        reward_cents=200,
    )
    db_session.add(chore)
    await db_session.flush()
    occ = ChoreOccurrence(
        household_id=household.id,
        chore_id=chore.id,
        assignee_id=child_user.id,
        window_open_at=datetime(2025, 1, 2, tzinfo=UTC),
        due_at=datetime(2025, 1, 2, 16, tzinfo=UTC),
        status=OccurrenceStatus.submitted,
        reward_cents=200,
    )
    db_session.add(occ)
    await db_session.flush()
    sub = Submission(occurrence_id=occ.id, submitter_id=child_user.id, kind="photo")
    db_session.add(sub)
    await db_session.flush()
    await db_session.commit()
    return occ, sub


async def test_enqueue_claim_complete(db_session, occ_and_sub):
    occ, sub = occ_and_sub
    job = await queue.enqueue(db_session, occurrence_id=occ.id, submission_id=sub.id)
    await db_session.commit()
    assert job.state == JobState.queued

    claimed = await queue.claim_one(db_session)
    assert claimed.id == job.id
    assert claimed.state == JobState.running and claimed.attempts == 1 and claimed.locked_at

    # Nothing else queued.
    assert await queue.claim_one(db_session) is None

    await queue.complete(db_session, claimed)
    await db_session.commit()
    assert claimed.state == JobState.done


async def test_retry_then_park_as_failed(db_session, occ_and_sub):
    occ, sub = occ_and_sub
    await queue.enqueue(db_session, occurrence_id=occ.id, submission_id=sub.id)
    await db_session.commit()

    for _ in range(queue.MAX_ATTEMPTS - 1):
        j = await queue.claim_one(db_session)
        await queue.fail(db_session, j, "boom")
        await db_session.commit()
        assert j.state == JobState.queued  # retried

    j = await queue.claim_one(db_session)
    await queue.fail(db_session, j, "boom")
    await db_session.commit()
    assert j.state == JobState.failed and j.attempts == queue.MAX_ATTEMPTS


async def test_requeue_stuck(db_session, occ_and_sub):
    occ, sub = occ_and_sub
    job = await queue.enqueue(db_session, occurrence_id=occ.id, submission_id=sub.id)
    old = datetime.now(UTC) - timedelta(minutes=30)
    job.state = JobState.running
    job.locked_at = old
    await db_session.commit()

    moved = await queue.requeue_stuck(db_session)
    await db_session.commit()
    assert moved == 1
    await db_session.refresh(job)
    assert job.state == JobState.queued and job.locked_at is None


async def test_skip_locked_hands_disjoint_jobs_to_two_workers(engine, occ_and_sub):
    occ, sub = occ_and_sub
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as seed:
        seed.add_all(VerificationJob(occurrence_id=occ.id, submission_id=sub.id) for _ in range(2))
        await seed.commit()

    async with maker() as s1, maker() as s2:
        await s1.begin()
        await s2.begin()
        j1 = await queue.claim_one(s1)
        j2 = await queue.claim_one(s2)
        assert j1 is not None and j2 is not None and j1.id != j2.id
        await s1.rollback()
        await s2.rollback()
