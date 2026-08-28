"""Phase 6: data-retention sweeps (spec §5, §6.2, §14 Q2)."""

from __future__ import annotations

import io
from datetime import UTC, date, datetime, time, timedelta

import pytest
from PIL import Image

from app.models import (
    Chore,
    ChoreOccurrence,
    OccurrenceStatus,
    Submission,
    SubmissionKind,
    SubmissionMedia,
)
from app.services import media as media_svc
from app.services import retention

pytestmark = pytest.mark.asyncio


@pytest.fixture
def media_root(tmp_path, monkeypatch):
    monkeypatch.setattr(media_svc, "_media_root", lambda: tmp_path)
    return tmp_path


def _jpeg(color=(120, 60, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (900, 700), color).save(buf, format="JPEG", quality=95)
    return buf.getvalue()


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
        photo_count=1,
        verification_mode="manual",
        reward_cents=200,
    )
    db.add(chore)
    await db.flush()
    occ = ChoreOccurrence(
        household_id=household.id,
        chore_id=chore.id,
        assignee_id=child.id,
        window_open_at=datetime(2025, 1, 2, tzinfo=UTC),
        due_at=datetime(2025, 1, 2, 16, tzinfo=UTC),
        status=OccurrenceStatus.open,
        reward_cents=200,
    )
    db.add(occ)
    await db.flush()
    return occ


async def _photo_submission(db, occ, *, age_days: int, color=(120, 60, 30)) -> SubmissionMedia:
    res = media_svc.ingest_photo(_jpeg(color), household_id=str(occ.household_id))
    sub = Submission(occurrence_id=occ.id, kind=SubmissionKind.photo)
    db.add(sub)
    await db.flush()
    sub.created_at = datetime.now(UTC) - timedelta(days=age_days)
    m = SubmissionMedia(
        submission_id=sub.id,
        idx=0,
        sha256=res.sha256,
        phash=res.phash,
        width=res.width,
        height=res.height,
        bytes=res.bytes,
        storage_path=res.storage_path,
    )
    db.add(m)
    await db.flush()
    return m


async def test_prune_media_thumbnails_and_deletes_old_originals(
    db_session, household, child_user, media_root
):
    occ = await _occurrence(db_session, household, child_user)
    old = await _photo_submission(db_session, occ, age_days=200)
    fresh = await _photo_submission(db_session, occ, age_days=3, color=(10, 40, 90))
    await db_session.commit()

    stats = await retention.prune_media(db_session)
    await db_session.commit()
    assert stats == {"thumbnailed": 1, "originals_deleted": 1}

    await db_session.refresh(old)
    await db_session.refresh(fresh)

    assert old.original_deleted_at is not None
    assert old.thumbnail_path and (media_root / old.thumbnail_path).is_file()
    assert not (media_root / old.storage_path).exists()
    thumb = Image.open(io.BytesIO(media_svc.read_media(old.thumbnail_path)))
    assert max(thumb.size) == media_svc.THUMB_LONG_EDGE

    # The still-fresh submission is untouched.
    assert fresh.original_deleted_at is None
    assert (media_root / fresh.storage_path).is_file()

    # Idempotent: a second sweep finds nothing.
    assert await retention.prune_media(db_session) == {"thumbnailed": 0, "originals_deleted": 0}


async def test_prune_media_keeps_original_shared_by_a_live_row(
    db_session, household, child_user, media_root
):
    occ = await _occurrence(db_session, household, child_user)
    old = await _photo_submission(db_session, occ, age_days=200, color=(7, 7, 7))
    # Same bytes -> same content-addressed path, but this row is not yet expired.
    dup_fresh = await _photo_submission(db_session, occ, age_days=1, color=(7, 7, 7))
    assert old.storage_path == dup_fresh.storage_path
    await db_session.commit()

    stats = await retention.prune_media(db_session)
    await db_session.commit()
    assert stats == {"thumbnailed": 1, "originals_deleted": 0}
    # Original file survives because dup_fresh still points at it.
    assert (media_root / old.storage_path).is_file()


async def test_pruned_media_endpoint_serves_the_thumbnail(
    client, db_session, household, admin_user, child_user, media_root, totp_now
):
    occ = await _occurrence(db_session, household, child_user)
    m = await _photo_submission(db_session, occ, age_days=200)
    await db_session.commit()
    await retention.prune_media(db_session)
    await db_session.commit()

    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "parent", "password": "parent-pass", "totp_code": totp_now()},
    )
    assert login.status_code == 200
    r = await client.get(f"/api/v1/submissions/{m.submission_id}/media/0")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert max(Image.open(io.BytesIO(r.content)).size) == media_svc.THUMB_LONG_EDGE


async def test_prune_geo_drops_the_point_but_keeps_the_boolean(db_session, household, child_user):
    occ = await _occurrence(db_session, household, child_user)
    old = Submission(
        occurrence_id=occ.id,
        kind=SubmissionKind.location,
        geo_lat=37.7749,
        geo_lon=-122.4194,
        geo_accuracy_m=12.0,
        geo_distance_m=8.0,
        geo_within=True,
        geo_captured_at=datetime.now(UTC) - timedelta(days=40),
    )
    fresh = Submission(
        occurrence_id=occ.id,
        kind=SubmissionKind.location,
        geo_lat=37.0,
        geo_lon=-122.0,
        geo_accuracy_m=10.0,
        geo_within=False,
        geo_captured_at=datetime.now(UTC) - timedelta(days=2),
    )
    db_session.add_all([old, fresh])
    await db_session.flush()
    old.created_at = datetime.now(UTC) - timedelta(days=40)
    fresh.created_at = datetime.now(UTC) - timedelta(days=2)
    await db_session.commit()

    n = await retention.prune_geo(db_session)
    await db_session.commit()
    assert n == 1

    await db_session.refresh(old)
    await db_session.refresh(fresh)
    assert old.geo_lat is None and old.geo_lon is None and old.geo_captured_at is None
    assert old.geo_within is True  # the result is kept
    assert fresh.geo_lat is not None  # too recent to prune

    assert await retention.prune_geo(db_session) == 0  # idempotent
