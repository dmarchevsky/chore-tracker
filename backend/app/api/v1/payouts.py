"""Payouts (spec §4.3, §9, §10)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.auth.deps import AdminUser, DbDep
from app.models import Household, LedgerEntry, LedgerKind, User, UserRole
from app.schemas.ledger import LedgerEntryOut, PayoutCreate
from app.services import audit, ledger

router = APIRouter(prefix="/payouts", tags=["payouts"])


@router.post("", response_model=LedgerEntryOut, status_code=status.HTTP_201_CREATED)
async def create_payout(body: PayoutCreate, db: DbDep, admin: AdminUser) -> LedgerEntry:
    child = await db.get(User, body.child_id)
    if child is None or child.role != UserRole.child:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "child not found")
    household = (await db.execute(select(Household).limit(1))).scalar_one()

    entry = await ledger.record_payout(
        db,
        child_id=child.id,
        household_id=household.id,
        amount_cents=body.amount_cents,
        method=body.method,
        note=body.note,
        actor=admin,
        covers_through=body.covers_through,
    )
    await audit.record(
        db,
        actor=admin,
        action="payout.create",
        entity_type="ledger_entry",
        entity_id=entry.id,
        after={
            "child_id": str(child.id),
            "amount_cents": entry.amount_cents,
            "method": body.method,
            "covers_through": body.covers_through.isoformat() if body.covers_through else None,
        },
    )
    await db.refresh(entry)
    return entry


@router.get("", response_model=list[LedgerEntryOut])
async def list_payouts(
    db: DbDep, _: AdminUser, child_id: uuid.UUID | None = None
) -> list[LedgerEntry]:
    stmt = (
        select(LedgerEntry)
        .where(LedgerEntry.kind == LedgerKind.payout)
        .order_by(LedgerEntry.created_at.desc())
    )
    if child_id is not None:
        stmt = stmt.where(LedgerEntry.child_id == child_id)
    return list((await db.execute(stmt)).scalars())
