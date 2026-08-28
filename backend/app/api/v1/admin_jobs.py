"""Operator dashboard data (spec §10 `GET /admin/jobs`).

Full dashboard (structured logs, alerting) is Phase 6; this exposes what already exists:
verification-queue depth, stuck jobs, recent failures, and check-in staleness so a broken
geofence automation surfaces as a config problem, not a penalised kid (spec §6.2).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from sqlalchemy import func, select

from app.auth.deps import AdminUser, DbDep
from app.models import CheckinToken, JobState, User, VerificationJob
from app.worker.queue import STUCK_AFTER_S, depth

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/jobs")
async def jobs_dashboard(db: DbDep, _: AdminUser) -> dict:
    now = datetime.now(UTC)
    queue = await depth(db)

    stuck = (
        await db.scalar(
            select(func.count())
            .select_from(VerificationJob)
            .where(
                VerificationJob.state == JobState.running,
                VerificationJob.locked_at < now - timedelta(seconds=STUCK_AFTER_S),
            )
        )
    ) or 0

    failures = (
        (
            await db.execute(
                select(VerificationJob)
                .where(VerificationJob.state == JobState.failed)
                .order_by(VerificationJob.updated_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )

    tokens = (
        await db.execute(
            select(CheckinToken, User.display_name)
            .join(User, User.id == CheckinToken.child_id)
            .where(CheckinToken.revoked_at.is_(None))
        )
    ).all()

    return {
        "queue": queue,
        "stuck_jobs": int(stuck),
        "recent_failures": [
            {"id": str(j.id), "occurrence_id": str(j.occurrence_id), "error": j.last_error}
            for j in failures
        ],
        "checkins": [
            {
                "child": name,
                "last_seen": t.last_used_at.isoformat() if t.last_used_at else None,
                "stale": t.last_used_at is None
                or (now - t.last_used_at).total_seconds() > 48 * 3600,
            }
            for t, name in tokens
        ],
    }


@router.get("/notifications")
async def recent_notifications(db: DbDep, _: AdminUser, limit: int = 50) -> list[dict]:
    from app.models import NotificationLog

    rows = (
        (
            await db.execute(
                select(NotificationLog).order_by(NotificationLog.created_at.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "kind": n.kind,
            "title": n.title,
            "body": n.body,
            "status": n.status,
            "created_at": n.created_at.isoformat(),
        }
        for n in rows
    ]
