"""Child-account management (admin) — spec §10 `/children`."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.auth.deps import AdminUser, DbDep
from app.auth.passwords import hash_password
from app.models import Household, User, UserRole
from app.schemas.user import PasswordReset, UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/children", tags=["children"])


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
async def create_child(payload: UserCreate, db: DbDep, _: AdminUser) -> User:
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
    return user


@router.get("/{child_id}", response_model=UserOut)
async def get_child(child_id: uuid.UUID, db: DbDep, _: AdminUser) -> User:
    return await _get_child(db, child_id)


@router.patch("/{child_id}", response_model=UserOut)
async def update_child(child_id: uuid.UUID, payload: UserUpdate, db: DbDep, _: AdminUser) -> User:
    user = await _get_child(db, child_id)
    if payload.display_name is not None:
        user.display_name = payload.display_name
    if payload.is_active is not None:
        user.is_active = payload.is_active
    return user


@router.post("/{child_id}/password-reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_child_password(
    child_id: uuid.UUID, payload: PasswordReset, db: DbDep, _: AdminUser
) -> None:
    # spec §15 Q4 default: admin resets a kid's password from the panel, no email.
    user = await _get_child(db, child_id)
    user.password_hash = hash_password(payload.new_password)


@router.delete("/{child_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_child(child_id: uuid.UUID, db: DbDep, _: AdminUser) -> None:
    # Soft disable — never delete, history hangs off this user (spec §4.1 `active`).
    user = await _get_child(db, child_id)
    user.is_active = False
