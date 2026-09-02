"""One-off: clear development residue and open the household's real books.

Six phases of building this left the database full of scaffolding — chores created to
exercise a feature and then deactivated, occurrences scattered over whatever dates a test
needed, and balances owed against chores that never existed. None of it is history anyone
should have to explain to a kid, so before the household goes live it is deleted rather
than reversed, every real chore is re-dated to ``BACKFILL_START``, and the days since are
rebuilt as if the family had been using the app all along.

This is a deliberate, one-time exception to the append-only ledger (spec §9): it DELETEs
money rows instead of writing compensating entries. That is defensible for clearing
development residue before anyone has been paid, and indefensible afterwards — hence the
``--yes`` guard, and the counts printed on both sides of the wipe.

Run:  docker compose exec -T api python -m app.prep_prod --yes
Take a backup first (``just backup dev``); there is no undo.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models import (
    Chore,
    ChoreOccurrence,
    Household,
    LedgerEntry,
    OccurrenceStatus,
    User,
    UserRole,
)
from app.models.chore import ChoreKind
from app.services import audit, ledger
from app.services.cadence import due_datetimes
from app.services.scheduler import generate_occurrences, resolve_assignees

# The day the household's books open. Every active chore starts here and the backfill runs
# from here to today.
BACKFILL_START = date(2026, 8, 31)

# Chores nobody actually did in the backfill window, so their occurrences land MISSED rather
# than approved. A named list because it is a statement about the family's real week, not a
# property of the chore — and the next person to run this will want to change it.
MISS_TITLES = {"Walk the dog"}

_APPROVED_REASON = "opening balance: chore done"


async def counts(db: AsyncSession) -> dict[str, int]:
    """The numbers worth printing on both sides of a destructive step."""
    out = {}
    for name, model in (
        ("chores", Chore),
        ("chore_occurrences", ChoreOccurrence),
        ("ledger_entries", LedgerEntry),
    ):
        out[name] = await db.scalar(select(func.count()).select_from(model)) or 0
    return out


async def balances(db: AsyncSession) -> dict[str, int]:
    rows = await db.execute(
        select(User.username, func.coalesce(func.sum(LedgerEntry.amount_cents), 0))
        .select_from(User)
        .outerjoin(LedgerEntry, LedgerEntry.child_id == User.id)
        .where(User.role == UserRole.child)
        .group_by(User.username)
        .order_by(User.username)
    )
    return dict(rows.all())


async def wipe_history(db: AsyncSession) -> dict[str, int]:
    """Delete every occurrence and every ledger row.

    Order matters only for readability — ``ledger_entries.occurrence_id`` is ON DELETE SET
    NULL precisely so deleting a chore can never delete the money it moved (spec §9), which
    means dropping occurrences alone would leave the balances behind as orphans. The ledger
    has to go explicitly, and it goes first.

    Occurrences cascade to submissions, submission_media, verifications, verification_jobs
    and disputes. Left standing on purpose: audit_log (the record of what happened, this run
    included), chore_state_events, push_subscriptions, sessions, users and household config.
    """
    n_ledger = (await db.execute(delete(LedgerEntry))).rowcount or 0
    n_occ = (await db.execute(delete(ChoreOccurrence))).rowcount or 0
    await db.flush()
    return {"ledger_entries": n_ledger, "chore_occurrences": n_occ}


async def drop_inactive_chores(db: AsyncSession) -> list[str]:
    """Hard-delete deactivated chores, and return their titles.

    The API's DELETE is a soft delete — it only flips ``active`` (api/v1/chores.py), because
    normally history hangs off the occurrences and must survive the rule. Here the history is
    being deleted too, so there is nothing left to protect.
    """
    titles = list(
        (await db.execute(select(Chore.title).where(Chore.active.is_(False)))).scalars().all()
    )
    await db.execute(delete(Chore).where(Chore.active.is_(False)))
    await db.flush()
    return titles


async def redate_active_chores(db: AsyncSession, *, start: date) -> int:
    """Move every active chore's start_date to ``start``.

    Applied to standing chores and penalty rules as well as scheduled ones: it is inert for
    those two (they never materialise an occurrence — services/cadence.py) but leaving them
    on a stale date would just invite the question of why they differ.
    """
    result = await db.execute(update(Chore).where(Chore.active.is_(True)).values(start_date=start))
    await db.flush()
    return result.rowcount or 0


async def backfill(
    db: AsyncSession,
    *,
    household: Household,
    start: date,
    end: date,
    now: datetime | None = None,
) -> dict[str, int]:
    """Materialise ``[start, end]`` as settled history — approved and paid, except MISS_TITLES.

    The scheduler cannot do this: ``generate_occurrences`` clamps its window to
    ``max(chore.start_date, today)`` (spec §8.1), so it only ever creates future rows. The
    cadence and rotation logic is reused here rather than reimplemented, so a backfilled row
    lands on exactly the date and assignee a real one would have.
    """
    now = now or datetime.now(UTC)
    tz = ZoneInfo(household.timezone)
    chores = (
        (
            await db.execute(
                select(Chore).where(Chore.active.is_(True), Chore.chore_kind == ChoreKind.scheduled)
            )
        )
        .scalars()
        .all()
    )

    report = {"approved": 0, "missed": 0, "earned_cents": 0, "skipped_existing": 0}
    for chore in chores:
        window_end = end if chore.end_date is None else min(chore.end_date, end)
        missed = chore.title in MISS_TITLES
        for due_at in due_datetimes(chore.cadence, start, window_end, chore.due_time, tz):
            for assignee_id in resolve_assignees(chore, due_at.astimezone(tz).date()):
                existing = await db.scalar(
                    select(ChoreOccurrence.id).where(
                        ChoreOccurrence.chore_id == chore.id,
                        ChoreOccurrence.due_at == due_at,
                        ChoreOccurrence.assignee_id == assignee_id,
                    )
                )
                if existing is not None:
                    report["skipped_existing"] += 1
                    continue

                occ = ChoreOccurrence(
                    household_id=household.id,
                    chore_id=chore.id,
                    assignee_id=assignee_id,
                    window_open_at=due_at + timedelta(seconds=chore.window_open_offset_s),
                    due_at=due_at,
                    status=OccurrenceStatus.missed if missed else OccurrenceStatus.approved,
                    # Money terms are snapshotted at generation so later edits to the chore
                    # never rewrite history (spec §3).
                    reward_cents=chore.reward_cents,
                    penalty_cents=chore.penalty_cents,
                    late_multiplier=chore.late_multiplier,
                    outcome_tiers=chore.outcome_tiers,
                    # A miss is settled the moment it is written, so the worker's settle scan
                    # has nothing left to do with it and the kid is never charged twice.
                    settled_at=now if missed else None,
                )
                db.add(occ)
                await db.flush()

                if missed:
                    report["missed"] += 1
                    if occ.penalty_cents:
                        await ledger.debit_penalty(
                            db, occurrence=occ, actor=None, reason="opening balance: chore missed"
                        )
                    continue

                report["approved"] += 1
                # An `anyone` occurrence carries a NULL assignee — approved, but there is
                # nobody to credit. A zero-reward chore gets no entry rather than a $0 line
                # on a kid's statement.
                if assignee_id is not None and chore.reward_cents:
                    await ledger.credit_earning(
                        db, occurrence=occ, actor=None, reason=_APPROVED_REASON
                    )
                    report["earned_cents"] += chore.reward_cents

    await db.flush()
    return report


async def prepare(
    db: AsyncSession, *, start: date = BACKFILL_START, now: datetime | None = None
) -> dict:
    """The whole operation, in one transaction the caller commits."""
    now = now or datetime.now(UTC)
    household = (await db.execute(select(Household).limit(1))).scalar_one()
    today = now.astimezone(ZoneInfo(household.timezone)).date()

    before = await counts(db)
    wiped = await wipe_history(db)
    dropped = await drop_inactive_chores(db)
    redated = await redate_active_chores(db, start=start)
    filled = await backfill(db, household=household, start=start, end=today, now=now)
    # Populate the forward horizon now rather than waiting on a worker tick. Idempotent
    # against the (chore_id, due_at, assignee_id) key, so it cannot duplicate today's rows.
    generated = await generate_occurrences(db, now=now)

    await audit.record(
        db,
        action="household.prepare_for_production",
        entity_type="household",
        entity_id=household.id,
        actor_kind="system",
        before=before,
        after={
            "wiped": wiped,
            "dropped_chores": dropped,
            "redated_chores": redated,
            "start_date": start.isoformat(),
            "backfill": filled,
            "generated_forward": generated,
        },
    )
    return {
        "before": before,
        "wiped": wiped,
        "dropped": dropped,
        "redated": redated,
        "backfill": filled,
        "generated": generated,
        "after": await counts(db),
        "balances": await balances(db),
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="actually do it — without this the script only reports what is there now",
    )
    args = parser.parse_args()

    async with SessionLocal() as db:
        if not args.yes:
            print("Nothing was changed. This is what is in the database right now:")
            for k, v in (await counts(db)).items():
                print(f"  {k:<18}: {v}")
            for name, cents in (await balances(db)).items():
                print(f"  balance {name:<10}: {cents / 100:.2f}")
            print("\nRe-run with --yes to wipe it and open the books. Back up first.")
            return

        report = await prepare(db)
        await db.commit()

    print("Prepared the household for production.\n")
    print("  before:")
    for k, v in report["before"].items():
        print(f"    {k:<18}: {v}")
    print(
        f"  deleted     : {report['wiped']['ledger_entries']} ledger entries, "
        f"{report['wiped']['chore_occurrences']} occurrences"
    )
    print(f"  dropped     : {len(report['dropped'])} deactivated chores {report['dropped'] or ''}")
    print(f"  re-dated    : {report['redated']} active chores to {BACKFILL_START}")
    b = report["backfill"]
    print(
        f"  backfilled  : {b['approved']} approved, {b['missed']} missed, "
        f"{b['earned_cents'] / 100:.2f} credited"
    )
    print(f"  generated   : {report['generated']} forward occurrences")
    print("  after:")
    for k, v in report["after"].items():
        print(f"    {k:<18}: {v}")
    for name, cents in report["balances"].items():
        print(f"    balance {name:<10}: {cents / 100:.2f}")


if __name__ == "__main__":
    asyncio.run(main())
