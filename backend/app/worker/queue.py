"""Postgres job queue for verification (spec §7.1).

``SELECT ... FOR UPDATE SKIP LOCKED`` lets multiple workers pull disjoint jobs without a
broker. A crashed worker leaves its row ``running``; ``requeue_stuck`` reclaims it on the
next startup (spec §8.3).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import JobState, VerificationJob

MAX_ATTEMPTS = 3
STUCK_AFTER_S = 600  # 10 minutes (spec §8.3)


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


async def enqueue(
    db: AsyncSession, *, occurrence_id: uuid.UUID, submission_id: uuid.UUID
) -> VerificationJob:
    job = VerificationJob(occurrence_id=occurrence_id, submission_id=submission_id)
    db.add(job)
    await db.flush()
    return job


async def claim_one(db: AsyncSession, *, now: datetime | None = None) -> VerificationJob | None:
    """Lock and mark one queued job as running. Caller commits after processing it."""
    job = (
        await db.execute(
            select(VerificationJob)
            .where(VerificationJob.state == JobState.queued)
            .order_by(VerificationJob.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()
    if job is None:
        return None
    job.state = JobState.running
    job.locked_at = _now(now)
    job.attempts += 1
    await db.flush()
    return job


async def complete(db: AsyncSession, job: VerificationJob) -> None:
    job.state = JobState.done
    job.locked_at = None
    job.last_error = None
    await db.flush()


async def fail(db: AsyncSession, job: VerificationJob, error: str) -> None:
    """Retry until MAX_ATTEMPTS, then park as failed."""
    job.last_error = error[:2000]
    job.locked_at = None
    job.state = JobState.failed if job.attempts >= MAX_ATTEMPTS else JobState.queued
    await db.flush()


async def requeue_stuck(
    db: AsyncSession, *, older_than_s: int = STUCK_AFTER_S, now: datetime | None = None
) -> int:
    cutoff = _now(now) - timedelta(seconds=older_than_s)
    result = await db.execute(
        update(VerificationJob)
        .where(VerificationJob.state == JobState.running, VerificationJob.locked_at < cutoff)
        .values(state=JobState.queued, locked_at=None)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount or 0


async def depth(db: AsyncSession) -> dict[str, int]:
    rows = await db.execute(
        select(VerificationJob.state, func.count()).group_by(VerificationJob.state)
    )
    return {str(state): count for state, count in rows.all()}
