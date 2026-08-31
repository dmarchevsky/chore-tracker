"""Chore definitions + preview (spec §4.1, §10).

Reads (`GET /chores`, `GET /chores/{id}`) are open to any signed-in user — kids get
read-only visibility of the chore definitions + amounts (spec §15 Q8), scoped to active
chores. All writes stay admin-only.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy import select

from app.auth.deps import AdminUser, CurrentUser, DbDep
from app.models import Chore, ChoreOccurrence, Household, OccurrenceStatus, User, UserRole
from app.schemas.chore import ChoreBase, ChoreCreate, ChoreOut, ChoreUpdate, OccurrencePreviewItem
from app.services import audit
from app.services.cadence import due_datetimes
from app.services.scheduler import resolve_assignees

router = APIRouter(prefix="/chores", tags=["chores"])

ApplyMode = Literal["forward", "future_generated"]


async def _household(db: DbDep) -> Household:
    return (await db.execute(select(Household).limit(1))).scalar_one()


async def _validate_assignees(db: DbDep, household_id: uuid.UUID, ids: list[uuid.UUID]) -> None:
    if not ids:
        return
    rows = (
        (
            await db.execute(
                select(User.id).where(
                    User.id.in_(ids),
                    User.household_id == household_id,
                    User.role == UserRole.child,
                    User.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    missing = set(ids) - set(rows)
    if missing:
        raise HTTPException(422, f"unknown or non-child assignee(s): {sorted(map(str, missing))}")


async def _drop_future_occurrences(db: DbDep, chore: Chore) -> int:
    """Delete not-yet-started future occurrences; the scheduler re-materialises them from
    the current definition on its next pass (spec §4.1)."""
    now = datetime.now(UTC)
    rows = (
        (
            await db.execute(
                select(ChoreOccurrence).where(
                    ChoreOccurrence.chore_id == chore.id,
                    ChoreOccurrence.due_at > now,
                    ChoreOccurrence.status.in_([OccurrenceStatus.pending, OccurrenceStatus.open]),
                )
            )
        )
        .scalars()
        .all()
    )
    for occ in rows:
        await db.delete(occ)
    return len(rows)


@router.get("", response_model=list[ChoreOut])
async def list_chores(db: DbDep, user: CurrentUser, include_inactive: bool = False) -> list[Chore]:
    stmt = select(Chore).order_by(Chore.title)
    # Kids see the active chore definitions only (spec §15 Q8); include_inactive is admin-only.
    if not include_inactive or user.role == UserRole.child:
        stmt = stmt.where(Chore.active.is_(True))
    return list((await db.execute(stmt)).scalars())


@router.post("", response_model=ChoreOut, status_code=status.HTTP_201_CREATED)
async def create_chore(payload: ChoreCreate, db: DbDep, admin: AdminUser) -> Chore:
    household = await _household(db)
    ids = list(payload.assignee_ids)
    if payload.fixed_assignee_id:
        ids.append(payload.fixed_assignee_id)
    await _validate_assignees(db, household.id, ids)

    chore = Chore(household_id=household.id, **_dump(payload))
    db.add(chore)
    await db.flush()
    await audit.record(
        db,
        actor=admin,
        action="chore.create",
        entity_type="chore",
        entity_id=chore.id,
        after={"title": chore.title},
    )
    await db.refresh(chore)
    return chore


@router.get("/{chore_id}", response_model=ChoreOut)
async def get_chore(chore_id: uuid.UUID, db: DbDep, user: CurrentUser) -> Chore:
    chore = await db.get(Chore, chore_id)
    if chore is None or (user.role == UserRole.child and not chore.active):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "chore not found")
    return chore


@router.patch("/{chore_id}", response_model=ChoreOut)
async def update_chore(
    chore_id: uuid.UUID,
    payload: ChoreUpdate,
    db: DbDep,
    admin: AdminUser,
    apply: Annotated[ApplyMode, Query()] = "forward",
) -> Chore:
    chore = await db.get(Chore, chore_id)
    if chore is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "chore not found")

    data = payload.model_dump(exclude_unset=True)
    before = {k: getattr(chore, k) for k in data}

    # Re-validate the *whole* definition with the patch merged in, so cross-field
    # invariants (fixed needs an assignee, rotating needs >=2 + period + anchor,
    # auto_fail <= auto_pass, photo proof needs photo_count) still hold and the JSONB
    # fields get the same normalisation as the create path.
    effective = {k: getattr(chore, k) for k in ChoreBase.model_fields}
    effective.update(data)
    try:
        validated = ChoreCreate.model_validate(effective)
    except ValidationError as exc:
        raise HTTPException(422, f"invalid chore update: {exc.errors()}") from exc

    if data.keys() & {"assignment_mode", "fixed_assignee_id", "assignee_ids"}:
        ids = list(validated.assignee_ids)
        if validated.fixed_assignee_id:
            ids.append(validated.fixed_assignee_id)
        await _validate_assignees(db, chore.household_id, ids)

    normalized = _dump(validated)
    for field in data:
        setattr(chore, field, normalized[field])
    await db.flush()

    regenerated = 0
    if apply == "future_generated":
        regenerated = await _drop_future_occurrences(db, chore)

    await audit.record(
        db,
        actor=admin,
        action="chore.update",
        entity_type="chore",
        entity_id=chore.id,
        before=_json(before),
        after=_json(data) | {"apply": apply, "dropped_future": regenerated},
    )
    await db.refresh(chore)
    return chore


@router.delete("/{chore_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_chore(chore_id: uuid.UUID, db: DbDep, admin: AdminUser) -> None:
    chore = await db.get(Chore, chore_id)
    if chore is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "chore not found")
    chore.active = False  # soft delete — history hangs off occurrences (spec §4.1)
    await db.flush()
    dropped = await _drop_future_occurrences(db, chore)  # stop generating work for it
    await audit.record(
        db,
        actor=admin,
        action="chore.deactivate",
        entity_type="chore",
        entity_id=chore.id,
        after={"dropped_future": dropped},
    )


@router.post("/preview", response_model=list[OccurrencePreviewItem])
async def preview_occurrences(
    payload: ChoreCreate,
    db: DbDep,
    _: AdminUser,
    count: Annotated[int, Query(ge=1, le=60)] = 12,
    from_date: date | None = None,
) -> list[OccurrencePreviewItem]:
    """Next ``count`` occurrences for an unsaved definition — no DB writes (spec §10)."""
    household = await _household(db)
    tz = ZoneInfo(household.timezone)
    transient = Chore(household_id=household.id, **_dump(payload))

    start = max(from_date or datetime.now(tz).date(), payload.start_date)
    horizon_end = start + timedelta(days=400)
    end = horizon_end if payload.end_date is None else min(payload.end_date, horizon_end)

    items: list[OccurrencePreviewItem] = []
    for due_at in due_datetimes(payload.cadence, start, end, payload.due_time, tz):
        window_open_at = due_at + timedelta(seconds=payload.window_open_offset_s)
        for assignee_id in resolve_assignees(transient, due_at.astimezone(tz).date()):
            items.append(
                OccurrencePreviewItem(
                    due_at=due_at, window_open_at=window_open_at, assignee_id=assignee_id
                )
            )
            if len(items) >= count:
                return items
    return items


def _dump(payload: ChoreCreate) -> dict:
    data = payload.model_dump()
    if data.get("geofence") is not None:
        data["geofence"] = payload.geofence.model_dump(mode="json")
    if data.get("verification_checklist") is not None:
        data["verification_checklist"] = [c.model_dump() for c in payload.verification_checklist]
    if data.get("rotation_period") is not None:
        data["rotation_period"] = str(data["rotation_period"])
    return data


def _jsonable(v: object) -> object:
    if hasattr(v, "isoformat"):  # date / time / datetime
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, Decimal):  # Numeric columns (thresholds, late_multiplier)
        return float(v)
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    return v


def _json(d: dict) -> dict:
    return {k: _jsonable(v) for k, v in d.items()}
