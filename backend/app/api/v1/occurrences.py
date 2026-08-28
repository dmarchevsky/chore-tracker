"""Occurrence read + assignee swap (spec §8.2, §10).

Submissions, decisions and disputes arrive in Phase 3.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.auth.deps import AdminUser, CurrentUser, DbDep
from app.models import ChoreOccurrence, OccurrenceStatus, User, UserRole
from app.models.occurrence import TERMINAL
from app.schemas.chore import AssigneeSwap, OccurrenceOut
from app.services import audit

router = APIRouter(prefix="/occurrences", tags=["occurrences"])


@router.get("", response_model=list[OccurrenceOut])
async def list_occurrences(
    db: DbDep,
    user: CurrentUser,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    status_: Annotated[OccurrenceStatus | None, Query(alias="status")] = None,
    child: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[ChoreOccurrence]:
    stmt = select(ChoreOccurrence).order_by(ChoreOccurrence.due_at).limit(limit)
    if user.role == UserRole.child:
        stmt = stmt.where(ChoreOccurrence.assignee_id == user.id)
    elif child is not None:
        stmt = stmt.where(ChoreOccurrence.assignee_id == child)
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


@router.patch("/{occurrence_id}/assignee", response_model=OccurrenceOut)
async def swap_assignee(
    occurrence_id: uuid.UUID,
    body: AssigneeSwap,
    db: DbDep,
    admin: AdminUser,
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
