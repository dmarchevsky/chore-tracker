"""Money ledger operations (spec §9).

Append-only, integer cents, no UPDATEs to existing rows. Earning/penalty writes are
exactly-once per occurrence via ``ON CONFLICT DO NOTHING`` against the partial unique index
— a double-clicked approve cannot double-pay. Corrections are reversing ``adjustment``
entries that also stamp ``reversed_by_entry_id`` on the original.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import obs
from app.models import ChoreOccurrence, LedgerEntry, LedgerKind, User

_EARN_WHERE = text("kind IN ('earning','penalty')")


async def balance_cents(db: AsyncSession, child_id: uuid.UUID) -> int:
    total = await db.scalar(
        select(func.coalesce(func.sum(LedgerEntry.amount_cents), 0)).where(
            LedgerEntry.child_id == child_id
        )
    )
    return int(total or 0)


def _late_adjusted(base_cents: int, occ: ChoreOccurrence) -> int:
    if not occ.was_late or occ.late_multiplier is None:
        return base_cents
    mult = Decimal(str(occ.late_multiplier))
    return int((Decimal(base_cents) * mult).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


async def _insert_earn_kind(
    db: AsyncSession,
    *,
    occ: ChoreOccurrence,
    kind: LedgerKind,
    amount_cents: int,
    reason: str,
    actor: User | None,
) -> LedgerEntry:
    """Insert an earning/penalty row, or return the one already there (exactly-once)."""
    values = {
        "household_id": occ.household_id,
        "child_id": occ.assignee_id,
        "occurrence_id": occ.id,
        "kind": kind,
        "amount_cents": amount_cents,
        "reason": reason,
        "created_by": "user" if actor else "system",
        "actor_user_id": actor.id if actor else None,
    }
    stmt = (
        pg_insert(LedgerEntry)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["occurrence_id", "kind"], index_where=_EARN_WHERE)
        .returning(LedgerEntry.id)
    )
    new_id = await db.scalar(stmt)
    if new_id is None:
        return (
            await db.execute(
                select(LedgerEntry).where(
                    LedgerEntry.occurrence_id == occ.id, LedgerEntry.kind == kind
                )
            )
        ).scalar_one()
    await db.flush()
    entry = await db.get(LedgerEntry, new_id)
    obs.log_ledger_entry(entry)
    return entry


async def credit_earning(
    db: AsyncSession,
    *,
    occurrence: ChoreOccurrence,
    actor: User | None = None,
    amount_override_cents: int | None = None,
    reason: str = "chore approved",
) -> LedgerEntry:
    base = amount_override_cents if amount_override_cents is not None else occurrence.reward_cents
    amount = base if amount_override_cents is not None else _late_adjusted(base, occurrence)
    return await _insert_earn_kind(
        db, occ=occurrence, kind=LedgerKind.earning, amount_cents=amount, reason=reason, actor=actor
    )


async def debit_penalty(
    db: AsyncSession,
    *,
    occurrence: ChoreOccurrence,
    actor: User | None = None,
    reason: str = "chore missed",
) -> LedgerEntry | None:
    if not occurrence.penalty_cents:
        return None  # penalties are opt-in per chore (spec §4.1)
    return await _insert_earn_kind(
        db,
        occ=occurrence,
        kind=LedgerKind.penalty,
        amount_cents=-abs(occurrence.penalty_cents),
        reason=reason,
        actor=actor,
    )


async def post_tier_outcome(
    db: AsyncSession,
    *,
    occurrence: ChoreOccurrence,
    tier: dict,
    actor: User | None,
    reason: str,
) -> LedgerEntry | None:
    """Move the money for a chosen outcome tier (spec §4.6, §9).

    The tier's ``amount_cents`` is signed, so the sign picks the kind: a positive tier is an
    ``earning``, a negative one a ``penalty``. Not ``adjustment`` for the first write — that
    would drop the row out from under the ``(occurrence_id, kind)`` partial unique index and
    lose the double-click protection that makes a decision exactly-once.

    But a tier *change* is a legitimate second money movement on the same occurrence, and
    ``_insert_earn_kind`` is ON CONFLICT DO NOTHING: it would silently swallow the new amount
    and hand back the stale row. So once the kind's slot is taken, post an ``adjustment``
    instead — append-only holds, the index is never violated, and the balance is right.
    """
    amount = tier.get("amount_cents") or 0
    if not amount:
        return None  # a text tier moves no money

    kind = LedgerKind.earning if amount > 0 else LedgerKind.penalty
    taken = await db.scalar(
        select(LedgerEntry.id)
        .where(LedgerEntry.occurrence_id == occurrence.id, LedgerEntry.kind == kind)
        .limit(1)
    )
    if taken is None:
        return await _insert_earn_kind(
            db, occ=occurrence, kind=kind, amount_cents=amount, reason=reason, actor=actor
        )
    return await record_adjustment(
        db,
        child_id=occurrence.assignee_id,
        household_id=occurrence.household_id,
        amount_cents=amount,
        actor=actor,
        reason=reason,
        occurrence_id=occurrence.id,
        meta={"tier_id": tier["id"]},
    )


async def reverse_entry(
    db: AsyncSession, *, entry: LedgerEntry, actor: User | None, reason: str
) -> LedgerEntry:
    """Compensating adjustment; leaves history intact (spec §3, §9)."""
    comp = LedgerEntry(
        household_id=entry.household_id,
        child_id=entry.child_id,
        occurrence_id=entry.occurrence_id,
        kind=LedgerKind.adjustment,
        amount_cents=-entry.amount_cents,
        reason=reason,
        created_by="user" if actor else "system",
        actor_user_id=actor.id if actor else None,
        meta={"reverses_entry_id": str(entry.id)},
    )
    db.add(comp)
    await db.flush()
    entry.reversed_by_entry_id = comp.id
    obs.log_ledger_entry(comp)
    return comp


async def record_adjustment(
    db: AsyncSession,
    *,
    child_id: uuid.UUID,
    household_id: uuid.UUID,
    amount_cents: int,
    actor: User | None,
    reason: str,
    occurrence_id: uuid.UUID | None = None,
    meta: dict | None = None,
) -> LedgerEntry:
    entry = LedgerEntry(
        household_id=household_id,
        child_id=child_id,
        occurrence_id=occurrence_id,
        kind=LedgerKind.adjustment,
        amount_cents=amount_cents,
        reason=reason,
        created_by="user" if actor else "system",
        actor_user_id=actor.id if actor else None,
        meta=meta,
    )
    db.add(entry)
    await db.flush()
    obs.log_ledger_entry(entry)
    return entry


async def record_payout(
    db: AsyncSession,
    *,
    child_id: uuid.UUID,
    household_id: uuid.UUID,
    amount_cents: int,
    method: str,
    note: str,
    actor: User | None,
    covers_through: date | None = None,
    now: datetime | None = None,
) -> LedgerEntry:
    """Negative ``payout`` entry + lock every covered occurrence's settlement (spec §9)."""
    entry = LedgerEntry(
        household_id=household_id,
        child_id=child_id,
        kind=LedgerKind.payout,
        amount_cents=-abs(amount_cents),
        reason=note or f"payout via {method}",
        created_by="user" if actor else "system",
        actor_user_id=actor.id if actor else None,
        meta={
            "method": method,
            "note": note,
            "covers_through": covers_through.isoformat() if covers_through else None,
        },
    )
    db.add(entry)
    await db.flush()
    obs.log_ledger_entry(entry)

    if covers_through is not None:
        lock_at = now or datetime.now(UTC)
        cutoff = datetime.combine(covers_through, datetime.max.time(), tzinfo=UTC)
        await db.execute(
            update(ChoreOccurrence)
            .where(
                ChoreOccurrence.assignee_id == child_id,
                ChoreOccurrence.due_at <= cutoff,
                ChoreOccurrence.settlement_locked_at.is_(None),
            )
            .values(settlement_locked_at=lock_at)
            .execution_options(synchronize_session=False)
        )
    return entry
