"""Data-retention jobs (spec §5, §14 Q2; implementation-plan Phase 6 item 4).

Two independent sweeps, both stateless and idempotent so the worker can run them on
every full pass and they no-op once caught up:

- ``prune_media`` — after ``MEDIA_RETENTION_DAYS`` replace each stored original with a
  256px thumbnail and delete the full-size file. The verdict lives on the ``verifications``
  row and is untouched.
- ``prune_geo`` — after ``GEO_RETENTION_DAYS`` drop the coarse lat/lon/accuracy/distance
  from a check-in, keeping only the ``geo_within`` boolean (spec §6.2: no location history).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Submission, SubmissionMedia
from app.services import media as media_svc

log = logging.getLogger("chorekeeper.retention")


async def prune_media(db: AsyncSession, *, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=get_settings().media_retention_days)

    rows = list(
        (
            await db.execute(
                select(SubmissionMedia)
                .join(Submission, Submission.id == SubmissionMedia.submission_id)
                .where(
                    SubmissionMedia.original_deleted_at.is_(None),
                    Submission.created_at < cutoff,
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return {"thumbnailed": 0, "originals_deleted": 0}

    touched_paths: set[str] = set()
    for m in rows:
        try:
            m.thumbnail_path = media_svc.write_thumbnail(m.storage_path)
        except media_svc.MediaError as exc:
            # Original already gone (manual cleanup, restore gap): still mark it pruned.
            log.warning("thumbnail skipped for %s: %s", m.storage_path, exc)
            m.thumbnail_path = m.thumbnail_path or None
        m.original_deleted_at = now
        touched_paths.add(m.storage_path)
    await db.flush()

    # Content-addressed storage: only unlink an original once no live row still points at it.
    deleted = 0
    for path in touched_paths:
        still_live = await db.scalar(
            select(func.count())
            .select_from(SubmissionMedia)
            .where(
                SubmissionMedia.storage_path == path,
                SubmissionMedia.original_deleted_at.is_(None),
            )
        )
        if not still_live and media_svc.delete_original(path):
            deleted += 1

    log.info("prune_media: %d thumbnailed, %d originals deleted", len(rows), deleted)
    return {"thumbnailed": len(rows), "originals_deleted": deleted}


async def prune_geo(db: AsyncSession, *, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=get_settings().geo_retention_days)

    result = await db.execute(
        update(Submission)
        .where(Submission.geo_lat.is_not(None), Submission.created_at < cutoff)
        .values(
            geo_lat=None,
            geo_lon=None,
            geo_accuracy_m=None,
            geo_distance_m=None,
            geo_captured_at=None,
        )
    )
    n = result.rowcount or 0
    if n:
        log.info("prune_geo: cleared coarse location on %d submission(s)", n)
    return n


async def run_all(db: AsyncSession, *, now: datetime | None = None) -> dict[str, int]:
    media_stats = await prune_media(db, now=now)
    geo_n = await prune_geo(db, now=now)
    return {**media_stats, "geo_cleared": geo_n}
