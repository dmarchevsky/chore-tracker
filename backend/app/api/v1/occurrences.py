"""Occurrence read, assignee swap, submissions, decisions, disputes (spec §3, §4, §10)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select

from app.auth.deps import AdminUser, CurrentUser, DbDep
from app.models import (
    Chore,
    ChoreOccurrence,
    OccurrenceStatus,
    User,
    UserRole,
)
from app.models.occurrence import SUBMITTABLE, TERMINAL
from app.models.verification import Verification
from app.schemas.chore import AssigneeSwap, OccurrenceOut
from app.schemas.submission import (
    DecisionRequest,
    DisputeRequest,
    GeoIn,
    SubmissionOut,
    VerificationOut,
)
from app.services import audit, notifications, review
from app.services.media import sign_media

router = APIRouter(prefix="/occurrences", tags=["occurrences"])

_INBOX = (OccurrenceStatus.needs_review, OccurrenceStatus.submitted, OccurrenceStatus.verified_fail)
_MAX_UPLOAD_BYTES = 12 * 1024 * 1024  # Cloudflare free-plan cap is 100MB; we downscale hard


@router.get("", response_model=list[OccurrenceOut])
async def list_occurrences(
    db: DbDep,
    user: CurrentUser,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    status_: Annotated[OccurrenceStatus | None, Query(alias="status")] = None,
    child: uuid.UUID | None = None,
    inbox: bool = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[ChoreOccurrence]:
    stmt = select(ChoreOccurrence).order_by(ChoreOccurrence.due_at).limit(limit)
    if user.role == UserRole.child:
        stmt = stmt.where(ChoreOccurrence.assignee_id == user.id)
    elif child is not None:
        stmt = stmt.where(ChoreOccurrence.assignee_id == child)
    if inbox:  # admin review queue (spec §4.2)
        stmt = stmt.where(ChoreOccurrence.status.in_(_INBOX))
    if from_ is not None:
        stmt = stmt.where(ChoreOccurrence.due_at >= from_)
    if to is not None:
        stmt = stmt.where(ChoreOccurrence.due_at <= to)
    if status_ is not None:
        stmt = stmt.where(ChoreOccurrence.status == status_)
    return list((await db.execute(stmt)).scalars())


async def _get_scoped(db: DbDep, user: User, occurrence_id: uuid.UUID) -> ChoreOccurrence:
    occ = await db.get(ChoreOccurrence, occurrence_id)
    if occ is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "occurrence not found")
    if user.role == UserRole.child and occ.assignee_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "occurrence not found")
    return occ


@router.get("/{occurrence_id}", response_model=OccurrenceOut)
async def get_occurrence(occurrence_id: uuid.UUID, db: DbDep, user: CurrentUser) -> ChoreOccurrence:
    return await _get_scoped(db, user, occurrence_id)


@router.get("/{occurrence_id}/verifications")
async def occurrence_verifications(
    occurrence_id: uuid.UUID, db: DbDep, user: CurrentUser
) -> list[dict]:
    """Verdicts newest-first. A child sees only the friendly message — never confidence
    numbers or anti-cheat flags (spec §11); the raw model I/O is admin-only via
    `/verifications/{id}`."""
    await _get_scoped(db, user, occurrence_id)
    rows = (
        (
            await db.execute(
                select(Verification)
                .where(Verification.occurrence_id == occurrence_id)
                .order_by(Verification.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    if user.role == UserRole.child:
        return [
            {
                "verdict": str(v.verdict),
                "child_message": v.child_message,
                "image_quality_issue": v.image_quality_issue,
                "created_at": v.created_at.isoformat(),
            }
            for v in rows
        ]
    return [VerificationOut.model_validate(v).model_dump(mode="json") for v in rows]


@router.patch("/{occurrence_id}/assignee", response_model=OccurrenceOut)
async def swap_assignee(
    occurrence_id: uuid.UUID, body: AssigneeSwap, db: DbDep, admin: AdminUser
) -> ChoreOccurrence:
    """Kids trade weeks — swap a single occurrence's assignee, with an audit entry (spec §8.2)."""
    occ = await db.get(ChoreOccurrence, occurrence_id)
    if occ is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "occurrence not found")
    if occ.status in TERMINAL or occ.status == OccurrenceStatus.missed:
        raise HTTPException(status.HTTP_409_CONFLICT, f"cannot reassign a {occ.status} occurrence")

    target = body.assignee_id
    if target is not None:
        who = await db.get(User, target)
        if who is None or who.role != UserRole.child or not who.is_active:
            raise HTTPException(422, "assignee must be an active child")

    before = str(occ.assignee_id) if occ.assignee_id else None
    occ.assignee_id = target
    await db.flush()
    await audit.record(
        db,
        actor=admin,
        action="occurrence.swap_assignee",
        entity_type="occurrence",
        entity_id=occ.id,
        before={"assignee_id": before},
        after={"assignee_id": str(target) if target else None},
    )
    await db.refresh(occ)
    return occ


def _parse_json_form(raw: str | None, field: str) -> dict | None:
    if not raw:
        return None
    try:
        val = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, f"{field} is not valid JSON") from exc
    if not isinstance(val, dict):
        raise HTTPException(422, f"{field} must be a JSON object")
    return val


@router.post("/{occurrence_id}/submissions", response_model=SubmissionOut, status_code=201)
async def create_submission(
    occurrence_id: uuid.UUID,
    db: DbDep,
    user: CurrentUser,
    files: Annotated[list[UploadFile], File()] = [],  # noqa: B006 - FastAPI form default
    note: Annotated[str | None, Form()] = None,
    geo: Annotated[str | None, Form()] = None,
    source: Annotated[str, Form()] = "camera",
    client_meta: Annotated[str | None, Form()] = None,
) -> dict:
    occ = await _get_scoped(db, user, occurrence_id)
    if occ.status not in SUBMITTABLE:
        raise HTTPException(status.HTTP_409_CONFLICT, f"occurrence is {occ.status}, not open")
    chore = await db.get(Chore, occ.chore_id)

    blobs: list[tuple[str, bytes]] = []
    for f in files:
        data = await f.read()
        if len(data) > _MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"{f.filename} exceeds the upload limit")
        blobs.append((f.filename or "upload", data))

    geo_dict = _parse_json_form(geo, "geo")
    if geo_dict is not None:
        geo_dict = GeoIn.model_validate(geo_dict).model_dump()

    try:
        sub = await review.ingest_submission(
            db,
            occurrence=occ,
            chore=chore,
            submitter=user,
            files=blobs,
            note=note,
            geo=geo_dict,
            source=source,
            client_meta=_parse_json_form(client_meta, "client_meta"),
        )
        await review.route_submission(db, occurrence=occ, chore=chore, submission=sub)
    except review.SubmissionError as exc:
        raise HTTPException(422, str(exc)) from exc

    await db.flush()
    await db.refresh(sub)
    data = SubmissionOut.model_validate(sub).model_dump()
    for m in data["media"]:
        m["url"] = sign_media(str(sub.id), m["idx"])
    return data


@router.post("/{occurrence_id}/decision", response_model=OccurrenceOut)
async def decide(
    occurrence_id: uuid.UUID, body: DecisionRequest, db: DbDep, admin: AdminUser
) -> ChoreOccurrence:
    occ = await db.get(ChoreOccurrence, occurrence_id)
    if occ is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "occurrence not found")
    try:
        await review.apply_decision(
            db,
            occurrence=occ,
            admin=admin,
            action=body.action,
            reason=body.reason,
            amount_override_cents=body.amount_override_cents,
        )
    except review.SubmissionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.flush()
    await db.refresh(occ)
    return occ


@router.post("/{occurrence_id}/dispute", status_code=202)
async def dispute(
    occurrence_id: uuid.UUID, body: DisputeRequest, db: DbDep, user: CurrentUser
) -> dict:
    occ = await _get_scoped(db, user, occurrence_id)
    await audit.record(
        db,
        actor=user,
        action="occurrence.dispute",
        entity_type="occurrence",
        entity_id=occ.id,
        after={"message": body.message, "status_at_dispute": occ.status},
    )
    await notifications.notify_dispute(db, occ, body.message)
    return {"status": "filed"}
