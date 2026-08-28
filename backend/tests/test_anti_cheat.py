"""Phase 4: anti-cheat heuristics (spec §6.1)."""

from __future__ import annotations

import io
import random
from datetime import UTC, date, datetime, time

import pytest
import pytest_asyncio
from PIL import Image

from app.models import Chore, ChoreOccurrence, OccurrenceStatus, Submission, SubmissionMedia
from app.services.anti_cheat import (
    DEDUP_WINDOW_DAYS,
    FLAG_DUPLICATE,
    FLAG_NO_EXIF,
    FLAG_SCREENSHOT,
    FLAG_STALE,
    looks_like_screenshot,
    scan_submission,
    stale_capture,
    static_flags,
)
from app.services.media import ingest_photo


def test_stale_capture_uses_15_min_threshold():
    recv = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
    assert stale_capture({"DateTimeOriginal": "2025:01:01 11:40:00"}, recv) is True
    assert stale_capture({"DateTimeOriginal": "2025:01:01 11:50:00"}, recv) is False
    assert stale_capture({}, recv) is False


def test_screenshot_heuristic():
    assert looks_like_screenshot(1170, 2532, {}) is True  # iPhone screen ~19.5:9
    assert looks_like_screenshot(1170, 2532, {"Make": "Apple"}) is False  # camera identified
    assert looks_like_screenshot(4032, 3024, {}) is True  # 4:3 with no camera info
    assert looks_like_screenshot(4000, 2600, {}) is False  # odd ratio, no match


def test_static_flags_bundle():
    flags = static_flags(1170, 2532, None, datetime(2025, 1, 1, tzinfo=UTC))
    assert FLAG_NO_EXIF in flags and FLAG_SCREENSHOT in flags


def test_dedup_window_is_120_days():
    assert DEDUP_WINDOW_DAYS == 120


@pytest.fixture
def media_root(tmp_path, monkeypatch):
    from app.services import media as media_svc

    monkeypatch.setattr(media_svc, "_media_root", lambda: tmp_path)
    return tmp_path


@pytest_asyncio.fixture
async def occ(db_session, household, child_user) -> ChoreOccurrence:
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
    o = ChoreOccurrence(
        household_id=household.id,
        chore_id=chore.id,
        assignee_id=child_user.id,
        window_open_at=datetime(2025, 1, 2, tzinfo=UTC),
        due_at=datetime(2025, 1, 2, 16, tzinfo=UTC),
        status=OccurrenceStatus.submitted,
        reward_cents=200,
    )
    db_session.add(o)
    await db_session.flush()
    return o


def _textured_jpeg(seed: int, w: int = 800, h: int = 600) -> bytes:
    """A blocky random pattern — has real gradients, so dHash is meaningful."""
    rng = random.Random(seed)
    img = Image.new("RGB", (w, h))
    px = img.load()
    block = 25
    for by in range(0, h, block):
        for bx in range(0, w, block):
            c = (rng.randrange(256), rng.randrange(256), rng.randrange(256))
            for y in range(by, min(by + block, h)):
                for x in range(bx, min(bx + block, w)):
                    px[x, y] = c
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


async def _submit_photo(db, occ, blob, *, created_at=None) -> tuple[Submission, SubmissionMedia]:
    res = ingest_photo(blob, household_id=str(occ.household_id))
    sub = Submission(occurrence_id=occ.id, kind="photo")
    if created_at:
        sub.created_at = created_at
    db.add(sub)
    await db.flush()
    media = SubmissionMedia(
        submission_id=sub.id,
        idx=0,
        sha256=res.sha256,
        phash=res.phash,
        width=res.width,
        height=res.height,
        bytes=res.bytes,
        storage_path=res.storage_path,
        exif=res.exif or None,
    )
    db.add(media)
    await db.flush()
    return sub, media


async def test_duplicate_detection_across_recent_submissions(db_session, occ, media_root):
    blob = _textured_jpeg(seed=7)
    await _submit_photo(db_session, occ, blob)
    await db_session.commit()

    again, _ = await _submit_photo(db_session, occ, blob)  # same image, new submission
    await db_session.commit()

    assert FLAG_DUPLICATE in await scan_submission(db_session, again)


async def test_distinct_images_are_not_flagged_duplicate(db_session, occ, media_root):
    await _submit_photo(db_session, occ, _textured_jpeg(seed=1))
    await db_session.commit()
    other, _ = await _submit_photo(db_session, occ, _textured_jpeg(seed=999, w=640, h=640))
    await db_session.commit()

    assert FLAG_DUPLICATE not in await scan_submission(db_session, other)


async def test_scan_includes_stale_capture(db_session, occ, media_root):
    sub, media = await _submit_photo(
        db_session, occ, _textured_jpeg(seed=3), created_at=datetime(2025, 6, 1, 12, tzinfo=UTC)
    )
    media.exif = {"DateTimeOriginal": "2025:06:01 11:30:00"}  # 30 min before receive
    await db_session.flush()

    flags = await scan_submission(db_session, sub)
    assert FLAG_STALE in flags


async def test_scan_flags_missing_exif(db_session, occ, media_root):
    sub, media = await _submit_photo(db_session, occ, _textured_jpeg(seed=5))
    media.exif = None
    await db_session.flush()
    flags = await scan_submission(db_session, sub)
    assert FLAG_NO_EXIF in flags
