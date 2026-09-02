"""Development seed data (spec §13.3).

One household, one admin (with a break-glass password for the prod stack), two children, and
the four example chores from the brief. Phase 3 adds 30 days of backdated occurrences in
mixed states so the UI is never empty.

Run:  uv run python -m app.seed        (idempotent — safe to re-run)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.auth.passwords import hash_password
from app.config import get_settings
from app.db import SessionLocal
from app.models import (
    Chore,
    ChoreOccurrence,
    Household,
    OccurrenceStatus,
    Submission,
    User,
    UserRole,
    Verdict,
    Verification,
)
from app.services import ledger
from app.services.cadence import due_datetimes
from app.services.scheduler import resolve_assignees

# A repeating pattern of terminal/in-flight states so every admin + kid view has content.
_STATUS_CYCLE = [
    OccurrenceStatus.approved,
    OccurrenceStatus.approved,
    OccurrenceStatus.approved,
    OccurrenceStatus.missed,
    OccurrenceStatus.rejected,
    OccurrenceStatus.submitted,
    OccurrenceStatus.needs_review,
    OccurrenceStatus.excused,
]

# Sign-in is Google via Cloudflare Access in production and the DEV_AUTH picker locally
# (spec §12.1), so what a seeded account needs is an email. The admin also gets the
# break-glass password — unusable on the dev stack, which 404s that route, but a seeded
# database is also what a production stack is bootstrapped from.
ADMIN = {
    "username": "parent",
    "display_name": "Parent",
    "email": "parent@example.com",
    "password": "parent-dev-pass",
}
CHILDREN = [
    {"username": "alice", "display_name": "Alice", "email": "alice@example.com"},
    {"username": "bea", "display_name": "Bea", "email": "bea@example.com"},
]


async def seed() -> None:
    async with SessionLocal() as db:
        household = (await db.execute(select(Household).limit(1))).scalar_one_or_none()
        if household is None:
            household = Household(name="Home", timezone="America/Los_Angeles", currency="USD")
            db.add(household)
            await db.flush()

        await _upsert_user(db, household.id, ADMIN, UserRole.admin)
        kids = {
            child["username"]: await _upsert_user(db, household.id, child, UserRole.child)
            for child in CHILDREN
        }

        await _seed_chores(db, household.id, kids["alice"], kids["bea"])
        await db.flush()
        await _seed_occurrences(db, household)
        await db.commit()

    async with SessionLocal() as db:
        n_chores = len((await db.execute(select(Chore.id))).all())
        n_occ = len((await db.execute(select(ChoreOccurrence.id))).all())

    print("Seed complete.")
    print(f"  chores:   {n_chores}")
    print(f"  occurrences: {n_occ}")
    print(f"  admin:    {ADMIN['username']} / {ADMIN['email']}")
    for child in CHILDREN:
        print(f"  child:    {child['username']} / {child['email']}")
    # Naming the door that actually works here: on the dev stack break-glass is 404, so
    # printing a password would send the reader to the one page that cannot let them in.
    if get_settings().dev_auth:
        print("\n  Sign in at http://localhost:5173 — pick a user, no password.")
    else:
        print(f"\n  Break-glass: {ADMIN['username']} / {ADMIN['password']} (LAN door only)")


async def _seed_chores(db, household_id, alice: User, bea: User) -> None:
    if (await db.execute(select(Chore.id).limit(1))).first() is not None:
        return

    anchor = date(2025, 1, 6)  # a Monday
    start = date(2025, 1, 1)
    db.add_all(
        [
            Chore(
                household_id=household_id,
                title="Kitchen: empty the sink",
                description="Sink empty, counters clear of dirty dishes.",
                assignment_mode="rotating",
                assignee_ids=[alice.id, bea.id],
                rotation_period="biweekly",
                rotation_anchor_date=anchor,
                cadence="daily",
                due_time=time(8, 0),
                start_date=start,
                proof_type="photo",
                photo_count=2,
                photo_prompts=["sink close-up", "wide shot of the counters"],
                verification_mode="llm_auto",
                verification_checklist=[
                    {
                        "id": 1,
                        "text": "Is the sink basin free of dishes, cups, pans and utensils?",
                        "required": True,
                    },
                    {
                        "id": 2,
                        "text": "Is the counter around the sink free of dirty dishes?",
                        "required": True,
                    },
                    {
                        "id": 3,
                        "text": "Is the visible area free of food waste or spills?",
                        "required": True,
                    },
                ],
                reward_cents=200,
            ),
            Chore(
                household_id=household_id,
                title="Tidy your bedroom",
                description="Floor clear, bed made, clothes put away.",
                assignment_mode="fixed",
                fixed_assignee_id=alice.id,
                cadence="weekly(on=[SAT])",
                due_time=time(10, 0),
                start_date=start,
                proof_type="photo",
                photo_count=1,
                photo_prompts=["wide shot of the whole room"],
                verification_mode="llm_assist",
                verification_checklist=[
                    {
                        "id": 1,
                        "text": "Is the floor clear of clothes and clutter?",
                        "required": True,
                    },
                    {"id": 2, "text": "Is the bed made?", "required": True},
                ],
                reward_cents=300,
            ),
            Chore(
                household_id=household_id,
                title="Walk the dog",
                description="A real walk around the block, not just the backyard.",
                assignment_mode="fixed",
                fixed_assignee_id=bea.id,
                cadence="daily",
                due_time=time(17, 0),
                grace_period_s=45 * 60,
                start_date=start,
                proof_type="photo",
                photo_count=1,
                photo_prompts=["the dog outside on the walk"],
                verification_mode="manual",
                reward_cents=150,
            ),
            Chore(
                household_id=household_id,
                title="Check in at school",
                description="Tap 'I'm at school' when you arrive.",
                assignment_mode="fixed",
                fixed_assignee_id=alice.id,
                cadence="weekdays",
                due_time=time(8, 5),
                window_open_offset_s=-35 * 60,
                grace_period_s=5 * 60,
                start_date=start,
                proof_type="location",
                photo_count=0,
                geofence={
                    "lat": 37.7749,
                    "lon": -122.4194,
                    "radius_m": 120,
                    "arrive_before": "08:10",
                },
                verification_mode="auto_accept",
                reward_cents=100,
            ),
        ]
    )
    await db.flush()


async def _seed_occurrences(db, household: Household) -> None:
    """~30 days of backdated occurrences in mixed states + a few in-flight items (spec §13.3)."""
    if (await db.execute(select(ChoreOccurrence.id).limit(1))).first() is not None:
        return

    tz = ZoneInfo(household.timezone)
    today = datetime.now(tz).date()
    window_start = today - timedelta(days=30)
    chores = (await db.execute(select(Chore))).scalars().all()

    n = 0
    for chore in chores:
        past_due = due_datetimes(
            chore.cadence, window_start, today - timedelta(days=1), chore.due_time, tz
        )
        future_due = due_datetimes(
            chore.cadence, today, today + timedelta(days=6), chore.due_time, tz
        )

        for i, due_at in enumerate(past_due):
            status = _STATUS_CYCLE[i % len(_STATUS_CYCLE)]
            occ = _mk_occ(household, chore, due_at, status)
            db.add(occ)
            await db.flush()
            await _apply_seed_money(db, chore, occ, status)
            if status in (OccurrenceStatus.submitted, OccurrenceStatus.needs_review):
                db.add(
                    Submission(
                        occurrence_id=occ.id,
                        submitter_id=occ.assignee_id,
                        kind="acknowledgement",
                        note="seed submission",
                    )
                )
            if status == OccurrenceStatus.needs_review:
                db.add(
                    Verification(
                        occurrence_id=occ.id,
                        kind="manual",
                        verdict=Verdict.needs_review,
                        reasoning="seed: low confidence",
                        created_by="system",
                    )
                )
            n += 1

        now = datetime.now(UTC)
        for due_at in future_due:
            window_open = due_at + timedelta(seconds=chore.window_open_offset_s)
            st = OccurrenceStatus.open if window_open <= now else OccurrenceStatus.pending
            db.add(_mk_occ(household, chore, due_at, st))
            n += 1

    await db.flush()


def _mk_occ(household, chore, due_at, status) -> ChoreOccurrence:
    assignee = resolve_assignees(chore, due_at.astimezone(ZoneInfo(household.timezone)).date())[0]
    return ChoreOccurrence(
        household_id=household.id,
        chore_id=chore.id,
        assignee_id=assignee,
        window_open_at=due_at + timedelta(seconds=chore.window_open_offset_s),
        due_at=due_at,
        status=status,
        reward_cents=chore.reward_cents,
        penalty_cents=chore.penalty_cents,
        late_multiplier=chore.late_multiplier,
    )


async def _apply_seed_money(db, chore, occ, status) -> None:
    if occ.assignee_id is None:
        return
    if status == OccurrenceStatus.approved:
        await ledger.credit_earning(db, occurrence=occ, reason="seed: approved")
    elif status in (OccurrenceStatus.rejected, OccurrenceStatus.missed) and chore.penalty_cents:
        await ledger.debit_penalty(db, occurrence=occ, reason=f"seed: {status}")


async def _upsert_user(db, household_id, spec, role: UserRole):
    existing = (
        await db.execute(select(User).where(User.username == spec["username"]))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    password = spec.get("password")
    user = User(
        household_id=household_id,
        username=spec["username"],
        display_name=spec["display_name"],
        role=role,
        email=spec["email"],
        password_hash=hash_password(password) if password else None,
    )
    db.add(user)
    await db.flush()
    return user


if __name__ == "__main__":
    asyncio.run(seed())
