"""Anti-cheat heuristics for photo submissions (spec §6.1).

Every flag is an *input to routing* — it forces NEEDS_REVIEW, never an auto-fail. False
accusations are worse than a missed cheat.

The two *metadata* flags (NO_EXIF, SCREENSHOT_SUSPECTED) only run on ``gallery`` uploads.
The in-app camera mandated by spec §6.1 [D] item 1 grabs frames to a canvas and encodes
them with ``toBlob``, which produces a JPEG with no EXIF at all — no Make/Model, no
DateTimeOriginal — and at the camera track's native 4:3 or 16:9 ratio. Both heuristics
therefore fire on *every* honest in-app capture, which is noise, not signal: it forced each
submission to NEEDS_REVIEW and buried the model's actual verdict. Against a file the kid
picked out of the gallery they mean something, so that is where they run. The live-capture
path is its own provenance signal; what still guards it is pHash dedup, STALE_CAPTURE, the
GALLERY_UPLOAD flag and the randomized prompt token (spec §6.1 items 2, 3, 5).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChoreOccurrence, Submission, SubmissionMedia, SubmissionSource
from app.services.media import hamming

DEDUP_WINDOW_DAYS = 120  # spec §6.1
PHASH_MAX_DISTANCE = 8  # dHash is 64-bit; <=8 differing bits is a near-duplicate
STALE_EXIF_MINUTES = 15  # spec §6.1
# Long/short-edge ratios typical of phone *screens* (not camera sensors).
_SCREEN_RATIOS = (16 / 9, 19.5 / 9, 20 / 9, 4 / 3, 3 / 2)
_RATIO_TOL = 0.03

FLAG_DUPLICATE = "DUPLICATE_SUSPECTED"
FLAG_STALE = "STALE_CAPTURE"
FLAG_NO_EXIF = "NO_EXIF"
FLAG_SCREENSHOT = "SCREENSHOT_SUSPECTED"
# Raised at ingest rather than by scan_submission, but they route the same way and the
# admin UI labels them from one list, so the names live here too.
FLAG_GALLERY = "GALLERY_UPLOAD"
FLAG_LOW_ACCURACY = "LOW_ACCURACY"
FLAG_OUTSIDE_FENCE = "OUTSIDE_GEOFENCE"


def _parse_exif_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def stale_capture(exif: dict | None, received_at: datetime) -> bool:
    dto = _parse_exif_dt((exif or {}).get("DateTimeOriginal"))
    if dto is None:
        return False
    return received_at - dto > timedelta(minutes=STALE_EXIF_MINUTES)


def looks_like_screenshot(width: int, height: int, exif: dict | None) -> bool:
    exif = exif or {}
    if exif.get("Make") or exif.get("Model"):
        return False  # a real camera identified itself
    if not width or not height:
        return False
    ratio = max(width, height) / min(width, height)
    return any(abs(ratio - r) <= _RATIO_TOL for r in _SCREEN_RATIOS)


def static_flags(
    width: int,
    height: int,
    exif: dict | None,
    received_at: datetime,
    *,
    metadata_checks: bool = True,
) -> list[str]:
    """Per-image checks that need no DB lookup.

    ``metadata_checks`` gates the two EXIF/dimension heuristics; see the module docstring
    for why they are meaningless on an in-app capture. STALE_CAPTURE runs either way — it
    needs a real DateTimeOriginal, so a canvas capture simply never trips it.
    """
    flags: list[str] = []
    if metadata_checks and not exif:
        flags.append(FLAG_NO_EXIF)
    if stale_capture(exif, received_at):
        flags.append(FLAG_STALE)
    if metadata_checks and looks_like_screenshot(width, height, exif):
        flags.append(FLAG_SCREENSHOT)
    return flags


async def _recent_phashes(
    db: AsyncSession, *, household_id, exclude_submission_id, now: datetime
) -> list[str]:
    cutoff = now - timedelta(days=DEDUP_WINDOW_DAYS)
    rows = await db.execute(
        select(SubmissionMedia.phash)
        .join(Submission, Submission.id == SubmissionMedia.submission_id)
        .join(ChoreOccurrence, ChoreOccurrence.id == Submission.occurrence_id)
        .where(
            ChoreOccurrence.household_id == household_id,
            Submission.id != exclude_submission_id,
            Submission.created_at >= cutoff,
            SubmissionMedia.phash.is_not(None),
        )
    )
    return [p for (p,) in rows.all() if p]


async def scan_submission(
    db: AsyncSession, submission: Submission, *, now: datetime | None = None
) -> list[str]:
    """Return the anti-cheat flags for a photo submission (deduplicated, order-stable)."""
    now = now or datetime.now(UTC)
    occ = await db.get(ChoreOccurrence, submission.occurrence_id)
    household_id = occ.household_id if occ else None

    media_rows = list(
        (
            await db.execute(
                select(SubmissionMedia).where(SubmissionMedia.submission_id == submission.id)
            )
        )
        .scalars()
        .all()
    )
    received_at = submission.created_at or now
    # Only a picked file could have carried camera metadata in the first place.
    metadata_checks = submission.source == SubmissionSource.gallery

    found: list[str] = []
    for media in media_rows:
        for f in static_flags(
            media.width,
            media.height,
            media.exif,
            received_at,
            metadata_checks=metadata_checks,
        ):
            if f not in found:
                found.append(f)

    if household_id is not None:
        neighbours = await _recent_phashes(
            db, household_id=household_id, exclude_submission_id=submission.id, now=now
        )
        for media in media_rows:
            if media.phash and any(
                hamming(media.phash, other) <= PHASH_MAX_DISTANCE for other in neighbours
            ):
                if FLAG_DUPLICATE not in found:
                    found.append(FLAG_DUPLICATE)
                break

    return found
