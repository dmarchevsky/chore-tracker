"""Admin view of kid-filed disputes (spec §4.2).

A dispute used to be fire-and-forget: an audit row plus a push, readable nowhere. It is a
kid telling a parent the system got it wrong, so it needs somewhere to land and a reply.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.auth.deps import AdminUser, DbDep
from app.models import Chore, ChoreOccurrence, Dispute, DisputeStatus, User
from app.schemas.dispute import DisputeResolve, DisputeWithContext
from app.services import disputes as dispute_svc

router = APIRouter(prefix="/disputes", tags=["disputes"])


@router.get("", response_model=list[DisputeWithContext])
async def list_disputes(
    db: DbDep,
    admin: AdminUser,
    status_: Annotated[DisputeStatus | None, Query(alias="status")] = DisputeStatus.open,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[dict]:
    stmt = (
        select(Dispute, Chore.title, User.display_name, ChoreOccurrence)
        .join(ChoreOccurrence, ChoreOccurrence.id == Dispute.occurrence_id)
        .join(Chore, Chore.id == ChoreOccurrence.chore_id)
        .outerjoin(User, User.id == Dispute.author_user_id)
        .order_by(Dispute.created_at.desc())
        .limit(limit)
    )
    if status_ is not None:
        stmt = stmt.where(Dispute.status == status_)

    out = []
    for d, chore_title, author_name, occ in (await db.execute(stmt)).all():
        row = DisputeWithContext.model_validate(d)
        row.chore_title = chore_title
        row.author_name = author_name
        row.occurrence_status = str(occ.status)
        row.occurrence_due_at = occ.due_at
        out.append(row.model_dump(mode="json"))
    return out


@router.post("/{dispute_id}/resolve", response_model=DisputeWithContext)
async def resolve_dispute(
    dispute_id: uuid.UUID, body: DisputeResolve, db: DbDep, admin: AdminUser
) -> Dispute:
    d = await db.get(Dispute, dispute_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dispute not found")
    try:
        await dispute_svc.resolve(db, dispute=d, admin=admin, note=body.note)
    except dispute_svc.DisputeError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.flush()
    await db.refresh(d)
    return d
