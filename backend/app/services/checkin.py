"""Check-in token management + webhook processing (spec §6.2).

A token can only transition a *location* occurrence that is currently OPEN; it can never
approve a photo chore or write an arbitrary ledger entry.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CheckinToken,
    Chore,
    ChoreOccurrence,
    OccurrenceStatus,
    Submission,
    SubmissionKind,
    SubmissionSource,
    User,
    UserRole,
)
from app.models.chore import ProofType
from app.services import review
from app.services.geo import evaluate_checkin

_LOCATION_PROOFS = {ProofType.location, ProofType.photo_location}


async def get_or_create_token(db: AsyncSession, child: User) -> CheckinToken:
    row = (
        await db.execute(select(CheckinToken).where(CheckinToken.child_id == child.id))
    ).scalar_one_or_none()
    if row is not None and row.active:
        return row
    if row is not None:
        row.token = secrets.token_urlsafe(32)
        row.revoked_at = None
        await db.flush()
        return row
    row = CheckinToken(child_id=child.id, token=secrets.token_urlsafe(32))
    db.add(row)
    await db.flush()
    return row


async def rotate_token(db: AsyncSession, child: User) -> CheckinToken:
    existing = (
        await db.execute(select(CheckinToken).where(CheckinToken.child_id == child.id))
    ).scalar_one_or_none()
    if existing is not None:
        existing.token = secrets.token_urlsafe(32)
        existing.revoked_at = None
        existing.last_used_at = None
        await db.flush()
        return existing
    return await get_or_create_token(db, child)


async def resolve_token(db: AsyncSession, token: str) -> tuple[CheckinToken, User] | None:
    row = (
        await db.execute(select(CheckinToken).where(CheckinToken.token == token))
    ).scalar_one_or_none()
    if row is None or not row.active:
        return None
    child = await db.get(User, row.child_id)
    if child is None or child.role != UserRole.child or not child.is_active:
        return None
    return row, child


async def _open_location_occurrence(
    db: AsyncSession, child_id: uuid.UUID
) -> tuple[ChoreOccurrence, Chore] | None:
    rows = (
        await db.execute(
            select(ChoreOccurrence, Chore)
            .join(Chore, Chore.id == ChoreOccurrence.chore_id)
            .where(
                ChoreOccurrence.assignee_id == child_id,
                ChoreOccurrence.status == OccurrenceStatus.open,
                Chore.proof_type.in_(list(_LOCATION_PROOFS)),
            )
            .order_by(ChoreOccurrence.due_at)
            .limit(1)
        )
    ).first()
    return (rows[0], rows[1]) if rows else None


async def process_checkin(
    db: AsyncSession,
    *,
    token_row: CheckinToken,
    child: User,
    lat: float,
    lon: float,
    accuracy: float,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(UTC)
    token_row.last_used_at = now

    found = await _open_location_occurrence(db, child.id)
    if found is None:
        return {"matched": False, "reason": "no open location check-in"}
    occ, chore = found

    fence = chore.geofence or {}
    chk = evaluate_checkin(
        lat=lat,
        lon=lon,
        accuracy_m=accuracy,
        center_lat=fence.get("lat", 0.0),
        center_lon=fence.get("lon", 0.0),
        radius_m=fence.get("radius_m", 0),
    )
    sub = Submission(
        occurrence_id=occ.id,
        submitter_id=child.id,
        kind=SubmissionKind.location,
        source=SubmissionSource.checkin_webhook,
        geo_lat=round(lat, 4),
        geo_lon=round(lon, 4),
        geo_accuracy_m=accuracy,
        geo_distance_m=round(chk.distance_m, 1),
        geo_within=chk.within,
        geo_captured_at=now,
        flags=review.geo_flags(chk),
    )
    db.add(sub)
    await db.flush()

    await review.route_submission(db, occurrence=occ, chore=chore, submission=sub)
    return {
        "matched": True,
        "within": chk.within,
        "distance_m": round(chk.distance_m, 1),
        "status": occ.status,
    }
