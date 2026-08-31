"""Filing and resolving kid disputes (spec §4.2, §6.3 rule 1)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChoreOccurrence, Dispute, DisputeStatus, User
from app.services import audit, notifications


class DisputeError(ValueError):
    """A dispute that cannot be filed or resolved in the current state."""


async def open_dispute(
    db: AsyncSession, *, occurrence: ChoreOccurrence, author: User, message: str
) -> Dispute:
    existing = await db.execute(
        select(Dispute).where(
            Dispute.occurrence_id == occurrence.id, Dispute.status == DisputeStatus.open
        )
    )
    if existing.scalars().first() is not None:
        raise DisputeError("a parent is already looking at this one")

    d = Dispute(
        occurrence_id=occurrence.id,
        author_user_id=author.id,
        message=message,
        status_at_filing=str(occurrence.status),
    )
    db.add(d)
    await db.flush()

    await audit.record(
        db,
        actor=author,
        action="occurrence.dispute",
        entity_type="occurrence",
        entity_id=occurrence.id,
        after={"dispute_id": str(d.id), "message": message, "status_at_dispute": occurrence.status},
    )
    await notifications.notify_dispute(db, occurrence, message)
    return d


async def resolve(db: AsyncSession, *, dispute: Dispute, admin: User, note: str) -> Dispute:
    # The column is a plain String, so a row loaded from the DB carries a str, not the
    # enum member — compare by value.
    if dispute.status == DisputeStatus.resolved:
        raise DisputeError("this dispute is already resolved")

    dispute.status = DisputeStatus.resolved
    dispute.resolution_note = note
    dispute.resolved_by_user_id = admin.id
    dispute.resolved_at = datetime.now(UTC)
    await db.flush()

    await audit.record(
        db,
        actor=admin,
        action="dispute.resolve",
        entity_type="dispute",
        entity_id=dispute.id,
        after={"note": note},
    )
    if dispute.author_user_id is not None:
        await notifications.notify_dispute_resolved(db, dispute, note)
    return dispute


async def for_occurrence(db: AsyncSession, occurrence_id: uuid.UUID) -> list[Dispute]:
    rows = await db.execute(
        select(Dispute)
        .where(Dispute.occurrence_id == occurrence_id)
        .order_by(Dispute.created_at.desc())
    )
    return list(rows.scalars().all())
