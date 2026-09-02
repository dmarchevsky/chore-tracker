"""Applying and undoing penalty rules (spec §4.8, §9, §10)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from app.auth.deps import AdminUser, DbDep
from app.models import Chore, LedgerEntry, User, UserRole
from app.schemas.ledger import LedgerEntryOut, PenaltyApplyRequest, PenaltyReverseRequest
from app.services import penalties

router = APIRouter(prefix="/penalties", tags=["penalties"])


@router.post("", response_model=LedgerEntryOut, status_code=status.HTTP_201_CREATED)
async def apply_penalty(body: PenaltyApplyRequest, db: DbDep, admin: AdminUser) -> LedgerEntry:
    chore = await db.get(Chore, body.chore_id)
    if chore is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "penalty rule not found")
    child = await db.get(User, body.child_id)
    if child is None or child.role != UserRole.child:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "child not found")

    try:
        entry = await penalties.apply(
            db,
            chore=chore,
            child=child,
            tier_id=body.tier_id,
            actor=admin,
            amount_override_cents=body.amount_override_cents,
            note=body.note,
        )
    except penalties.PenaltyError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    await db.refresh(entry)
    return entry


@router.post(
    "/{entry_id}/reverse", response_model=LedgerEntryOut, status_code=status.HTTP_201_CREATED
)
async def reverse_penalty(
    entry_id: uuid.UUID, body: PenaltyReverseRequest, db: DbDep, admin: AdminUser
) -> LedgerEntry:
    entry = await db.get(LedgerEntry, entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ledger entry not found")
    try:
        comp = await penalties.reverse(db, entry=entry, actor=admin, reason=body.reason)
    except penalties.PenaltyError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.refresh(comp)
    return comp
