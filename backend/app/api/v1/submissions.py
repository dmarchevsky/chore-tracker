"""Media serving + verification detail (spec §5, §10).

Media is served only here, with authz on every request — never as static files. A request
is allowed if it carries a valid short-lived signature, or a session belonging to an admin
or the kid the occurrence is assigned to.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.auth import SESSION_COOKIE
from app.auth.deps import AdminUser, CurrentUser, DbDep
from app.auth.sessions import load_session
from app.models import ChoreOccurrence, Submission, UserRole, Verification
from app.schemas.submission import SubmissionOut, VerificationRawOut
from app.services.media import MediaError, read_media, sign_media, verify_media_sig

router = APIRouter(tags=["media"])


def _with_urls(sub: Submission) -> dict:
    data = SubmissionOut.model_validate(sub).model_dump()
    for m in data["media"]:
        m["url"] = sign_media(str(sub.id), m["idx"])
    return data


async def _load_submission(db: DbDep, submission_id: uuid.UUID) -> Submission:
    sub = (
        await db.execute(
            select(Submission)
            .where(Submission.id == submission_id)
            .options(selectinload(Submission.media))
        )
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "submission not found")
    return sub


async def _may_view(db: DbDep, request: Request, sub: Submission) -> bool:
    sid = request.cookies.get(SESSION_COOKIE)
    loaded = await load_session(db, sid) if sid else None
    if loaded is None:
        return False
    _, user = loaded
    if user.role == UserRole.admin:
        return True
    occ = await db.get(ChoreOccurrence, sub.occurrence_id)
    return occ is not None and occ.assignee_id == user.id


@router.get("/submissions/{submission_id}", response_model=SubmissionOut)
async def get_submission(submission_id: uuid.UUID, db: DbDep, user: CurrentUser) -> dict:
    sub = await _load_submission(db, submission_id)
    if user.role != UserRole.admin:
        occ = await db.get(ChoreOccurrence, sub.occurrence_id)
        if occ is None or occ.assignee_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "submission not found")
    return _with_urls(sub)


@router.get("/submissions/{submission_id}/media/{idx}")
async def get_media(
    submission_id: uuid.UUID,
    idx: int,
    db: DbDep,
    request: Request,
    exp: str | None = None,
    sig: str | None = None,
) -> Response:
    signed_ok = bool(sig) and verify_media_sig(str(submission_id), idx, exp or "", sig or "")
    sub = await _load_submission(db, submission_id)
    if not signed_ok and not await _may_view(db, request, sub):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not authorized for this media")

    media = next((m for m in sub.media if m.idx == idx), None)
    if media is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "media not found")
    # After retention pruning only the 256px thumbnail survives (spec §14 Q2).
    path = media.thumbnail_path if media.original_deleted_at else media.storage_path
    if path is None:
        raise HTTPException(status.HTTP_410_GONE, "media pruned by retention policy")
    try:
        data = read_media(path)
    except MediaError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    return Response(
        content=data,
        media_type=media.mime,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/verifications/{verification_id}", response_model=VerificationRawOut)
async def get_verification(verification_id: uuid.UUID, db: DbDep, _: AdminUser) -> Verification:
    v = await db.get(Verification, verification_id)
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "verification not found")
    return v
