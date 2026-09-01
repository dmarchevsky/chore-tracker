"""Child-account management + balances/statements — spec §4.3, §10 `/children`."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select

from app.auth.deps import AdminUser, DbDep, require_self_or_admin
from app.auth.passwords import hash_password
from app.auth.sessions import revoke_user_sessions
from app.config import get_settings
from app.models import (
    CheckinToken,
    Chore,
    ChoreOccurrence,
    Household,
    LedgerEntry,
    User,
    UserRole,
)
from app.schemas.ledger import BalanceOut, LedgerEntryOut
from app.schemas.user import CheckinTokenOut, PasswordReset, UserCreate, UserOut, UserUpdate
from app.services import audit, checkin
from app.services.ledger import balance_cents

router = APIRouter(prefix="/children", tags=["children"])

SelfOrAdmin = Annotated[User, Depends(require_self_or_admin("child_id"))]


async def _get_child(db: DbDep, child_id: uuid.UUID) -> User:
    user = await db.get(User, child_id)
    if user is None or user.role != UserRole.child:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "child not found")
    return user


@router.get("", response_model=list[UserOut])
async def list_children(db: DbDep, _: AdminUser) -> list[User]:
    rows = await db.execute(
        select(User).where(User.role == UserRole.child).order_by(User.display_name)
    )
    return list(rows.scalars())


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_child(payload: UserCreate, db: DbDep, admin: AdminUser) -> User:
    if payload.role != UserRole.child:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "this endpoint creates child accounts")
    household = (await db.execute(select(Household).limit(1))).scalar_one()
    exists = (
        await db.execute(select(User).where(User.username == payload.username))
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "username taken")
    user = User(
        household_id=household.id,
        username=payload.username,
        display_name=payload.display_name,
        role=UserRole.child,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    await db.flush()
    await audit.record(
        db,
        actor=admin,
        action="child.create",
        entity_type="user",
        entity_id=user.id,
        after={"username": user.username, "display_name": user.display_name},
    )
    return user


@router.get("/{child_id}", response_model=UserOut)
async def get_child(child_id: uuid.UUID, db: DbDep, _: AdminUser) -> User:
    return await _get_child(db, child_id)


@router.patch("/{child_id}", response_model=UserOut)
async def update_child(
    child_id: uuid.UUID, payload: UserUpdate, db: DbDep, admin: AdminUser
) -> User:
    user = await _get_child(db, child_id)
    before = {"display_name": user.display_name, "is_active": user.is_active}
    if payload.display_name is not None:
        user.display_name = payload.display_name
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if not user.is_active:
        await revoke_user_sessions(db, user.id)  # a disabled kid is logged out now
    await audit.record(
        db,
        actor=admin,
        action="child.update",
        entity_type="user",
        entity_id=user.id,
        before=before,
        after={"display_name": user.display_name, "is_active": user.is_active},
    )
    return user


@router.post("/{child_id}/password-reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_child_password(
    child_id: uuid.UUID, payload: PasswordReset, db: DbDep, admin: AdminUser
) -> None:
    # spec §15 Q4 default: admin resets a kid's password from the panel, no email.
    user = await _get_child(db, child_id)
    user.password_hash = hash_password(payload.new_password)
    await revoke_user_sessions(db, user.id)  # force re-login with the new password
    await audit.record(
        db, actor=admin, action="child.password_reset", entity_type="user", entity_id=user.id
    )


@router.delete("/{child_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_child(child_id: uuid.UUID, db: DbDep, admin: AdminUser) -> None:
    # Soft disable — never delete, history hangs off this user (spec §4.1 `active`).
    user = await _get_child(db, child_id)
    user.is_active = False
    await revoke_user_sessions(db, user.id)
    await audit.record(
        db, actor=admin, action="child.deactivate", entity_type="user", entity_id=user.id
    )


@router.get("/{child_id}/balance", response_model=BalanceOut)
async def get_balance(child_id: uuid.UUID, db: DbDep, _: SelfOrAdmin) -> BalanceOut:
    await _get_child(db, child_id)
    # Balance may be negative — penalties are allowed to drive it below zero (spec §15 Q3).
    return BalanceOut(child_id=child_id, balance_cents=await balance_cents(db, child_id))


async def _ledger_rows(
    db: DbDep, child_id: uuid.UUID, from_: datetime | None, to: datetime | None
) -> list[LedgerEntryOut]:
    """The statement, with the chore each entry was for. Outer-joined: a payout or a
    hand-entered adjustment has no occurrence, and an occurrence whose chore was hard-deleted
    still has to show its money (spec §9, append-only)."""
    stmt = (
        select(LedgerEntry, Chore.title, ChoreOccurrence.due_at)
        .outerjoin(ChoreOccurrence, ChoreOccurrence.id == LedgerEntry.occurrence_id)
        .outerjoin(Chore, Chore.id == ChoreOccurrence.chore_id)
        .where(LedgerEntry.child_id == child_id)
        .order_by(LedgerEntry.created_at)
    )
    if from_ is not None:
        stmt = stmt.where(LedgerEntry.created_at >= from_)
    if to is not None:
        stmt = stmt.where(LedgerEntry.created_at <= to)
    return [
        LedgerEntryOut.model_validate(entry).model_copy(
            update={"chore_title": title, "occurrence_due_at": due_at}
        )
        for entry, title, due_at in (await db.execute(stmt)).all()
    ]


@router.get("/{child_id}/ledger", response_model=list[LedgerEntryOut])
async def get_ledger(
    child_id: uuid.UUID,
    db: DbDep,
    _: SelfOrAdmin,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
) -> list[LedgerEntryOut]:
    await _get_child(db, child_id)
    return await _ledger_rows(db, child_id, from_, to)


@router.get("/{child_id}/ledger.csv")
async def get_ledger_csv(
    child_id: uuid.UUID,
    db: DbDep,
    _: SelfOrAdmin,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
) -> Response:
    await _get_child(db, child_id)
    rows = await _ledger_rows(db, child_id, from_, to)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        ["created_at", "kind", "amount_cents", "currency", "reason", "chore", "occurrence_id"]
    )
    for r in rows:
        w.writerow(
            [
                r.created_at.isoformat(),
                r.kind,
                r.amount_cents,
                r.currency,
                r.reason,
                r.chore_title or "",
                r.occurrence_id or "",
            ]
        )
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="ledger-{child_id}.csv"'},
    )


def _token_out(row: CheckinToken) -> CheckinTokenOut:
    base = get_settings().public_base_url.rstrip("/")
    stale = (
        row.last_used_at is None
        or (datetime.now(row.last_used_at.tzinfo) - row.last_used_at).total_seconds() > 48 * 3600
    )
    return CheckinTokenOut(
        token=row.token,
        webhook_url=f"{base}/api/v1/checkin/{row.token}",
        last_used_at=row.last_used_at,
        stale=stale,
    )


@router.get("/{child_id}/checkin-token", response_model=CheckinTokenOut)
async def get_checkin_token(child_id: uuid.UUID, db: DbDep, _: AdminUser) -> CheckinTokenOut:
    child = await _get_child(db, child_id)
    return _token_out(await checkin.get_or_create_token(db, child))


@router.post("/{child_id}/checkin-token/rotate", response_model=CheckinTokenOut)
async def rotate_checkin_token(child_id: uuid.UUID, db: DbDep, _: AdminUser) -> CheckinTokenOut:
    child = await _get_child(db, child_id)
    return _token_out(await checkin.rotate_token(db, child))
