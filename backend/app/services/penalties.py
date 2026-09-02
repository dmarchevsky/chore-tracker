"""Applying a penalty rule to a kid (spec §4.8).

A penalty rule is a ``Chore`` with ``chore_kind="penalty"``: a published price list of
conditions, each with what it costs. It has no schedule and no occurrences, so applying it
*is* the whole lifecycle — and the ledger entry is the record of it, which is why the entry
carries ``chore_id``.

Charging is not idempotent on purpose. A parent may legitimately charge the same rule twice
in a day, and there is no occurrence to make "the same charge" mean anything.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chore, ChoreKind, LedgerEntry, LedgerKind, User
from app.services import audit, ledger, notifications
from app.services.scheduler import resolve_assignees


class PenaltyError(ValueError):
    """Raised for a charge that doesn't apply to this rule, kid or entry."""


async def apply(
    db: AsyncSession,
    *,
    chore: Chore,
    child: User,
    tier_id: int,
    actor: User | None,
    amount_override_cents: int | None = None,
    note: str | None = None,
    now: datetime | None = None,
) -> LedgerEntry:
    # chore_kind is a plain String column, so a row loaded in a later request carries a str,
    # not the enum member — `is not` would silently match nothing (same trap as standing.py).
    if chore.chore_kind != ChoreKind.penalty:
        raise PenaltyError("only a penalty rule can be applied")
    if not chore.active:
        raise PenaltyError("this penalty rule is deactivated")

    now = now or datetime.now(UTC)
    # fixed/all are the only modes _check_penalty allows, and resolve_assignees ignores the
    # date for both — it is passed for documentation, not as an input.
    if child.id not in resolve_assignees(chore, now.date()):
        raise PenaltyError(f"this rule does not apply to {child.display_name or child.username}")

    tier = next((t for t in (chore.outcome_tiers or []) if t["id"] == tier_id), None)
    if tier is None:
        raise PenaltyError(f"tier {tier_id} is not one of this rule's conditions")

    amount = -abs(amount_override_cents or tier["amount_cents"])
    # The kid reads this line on their statement, so it says the rule and the condition, not
    # a bare "penalty". The note is the parent's own words and goes last.
    reason = f"{chore.title}: {tier['condition']}"
    if note and note.strip():
        reason = f"{reason} — {note.strip()}"

    entry = await ledger.record_manual_penalty(
        db,
        child_id=child.id,
        household_id=chore.household_id,
        chore_id=chore.id,
        amount_cents=amount,
        actor=actor,
        reason=reason,
        # The tier is snapshotted, like an occurrence's: editing the rule later must not
        # rewrite what the kid was told they were charged for.
        meta={"tier_id": tier_id, "tier": tier, "note": note},
    )

    await audit.record(
        db,
        actor=actor,
        action="penalty.apply",
        entity_type="ledger_entry",
        entity_id=entry.id,
        after={
            "chore_id": str(chore.id),
            "child_id": str(child.id),
            "tier_id": tier_id,
            "amount_cents": entry.amount_cents,
            "note": note,
        },
    )
    await notifications.notify_penalty_applied(
        db, chore, child_id=child.id, tier=tier, amount_cents=entry.amount_cents, note=note
    )
    return entry


async def reverse(
    db: AsyncSession, *, entry: LedgerEntry, actor: User | None, reason: str
) -> LedgerEntry:
    """Undo an applied penalty with a compensating entry (spec §9, append-only).

    Scoped to manual penalties: an occurrence-backed penalty is undone by excusing the
    occurrence, which also clears the occurrence's own state. Reversing it from here would
    move the money back while leaving the occurrence still reading as a charged miss.
    """
    if entry.kind != LedgerKind.penalty or entry.occurrence_id is not None or not entry.chore_id:
        raise PenaltyError("only a manually applied penalty can be undone here")
    if entry.reversed_by_entry_id is not None:
        raise PenaltyError("this penalty has already been undone")

    comp = await ledger.reverse_entry(db, entry=entry, actor=actor, reason=reason)
    await audit.record(
        db,
        actor=actor,
        action="penalty.reverse",
        entity_type="ledger_entry",
        entity_id=entry.id,
        after={"reversed_by_entry_id": str(comp.id), "reason": reason},
    )
    return comp
