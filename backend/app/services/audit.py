"""Audit-trail helper (spec §5: every admin override recorded with actor + before/after)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Household, User


async def record(
    db: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: str | uuid.UUID | None = None,
    actor: User | None = None,
    actor_kind: str = "user",
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditLog:
    household_id = (
        actor.household_id if actor else (await db.execute(select(Household.id))).scalar_one()
    )
    entry = AuditLog(
        household_id=household_id,
        actor_user_id=actor.id if actor else None,
        actor_kind="user" if actor else actor_kind,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        before=before,
        after=after,
    )
    db.add(entry)
    await db.flush()
    return entry
