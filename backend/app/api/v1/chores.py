"""Chore definitions + preview (spec §4.1, §10).

TODO(decision): Q8 — kids get read-only visibility of chore definitions. Deferred to the
kid PWA (Phase 5); these endpoints are admin-only for now.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.auth.deps import AdminUser, DbDep
from app.models import Chore, ChoreOccurrence, Household, OccurrenceStatus, User, UserRole
from app.schemas.chore import ChoreCreate, ChoreOut, ChoreUpdate, OccurrencePreviewItem
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


def _apply_payload_to_model(chore: Chore, data: dict) -> None:
    for field, value in data.items():
        setattr(chore, field, value)


@router.get("", response_model=list[ChoreOut])
async def list_chores(db: DbDep, _: AdminUser, include_inactive: bool = False) -> list[Chore]:
    stmt = select(Chore).order_by(Chore.title)
    if not include_inactive:
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
async def get_chore(chore_id: uuid.UUID, db: DbDep, _: AdminUser) -> Chore:
    chore = await db.get(Chore, chore_id)
    if chore is None:
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
    _apply_payload_to_model(chore, data)
    await db.flush()

    regenerated = 0
    if apply == "future_generated":
        # Drop not-yet-started future occurrences; the scheduler re-materialises them
        # from the new definition on its next pass (spec §4.1 "apply to all future").
        now = datetime.now(UTC)
        rows = (
            (
                await db.execute(
                    select(ChoreOccurrence).where(
                        ChoreOccurrence.chore_id == chore.id,
                        ChoreOccurrence.due_at > now,
                        ChoreOccurrence.status.in_(
                            [OccurrenceStatus.pending, OccurrenceStatus.open]
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        for occ in rows:
            await db.delete(occ)
        regenerated = len(rows)

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
    await audit.record(
        db, actor=admin, action="chore.deactivate", entity_type="chore", entity_id=chore.id
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


def _json(d: dict) -> dict:
    out: dict = {}
    for k, v in d.items():
        out[k] = v.isoformat() if hasattr(v, "isoformat") else v
    return out
