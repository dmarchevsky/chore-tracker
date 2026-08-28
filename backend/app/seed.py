"""Development seed data (spec §13.3).

One household, one admin (TOTP pre-enrolled with a fixed dev secret), two children, and
the four example chores from the brief. Phase 3 adds 30 days of backdated occurrences in
mixed states so the UI is never empty.

Run:  uv run python -m app.seed        (idempotent — safe to re-run)
"""

from __future__ import annotations

import asyncio
from datetime import date, time

import pyotp
from sqlalchemy import select

from app.auth.passwords import hash_password
from app.db import SessionLocal
from app.models import Chore, Household, User, UserRole

# Fixed so a developer can add it to an authenticator app once.
DEV_ADMIN_TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"

ADMIN = {"username": "parent", "display_name": "Parent", "password": "parent-dev-pass"}
CHILDREN = [
    {"username": "alice", "display_name": "Alice", "password": "alice-dev-pass"},
    {"username": "bea", "display_name": "Bea", "password": "bea-dev-pass"},
]


async def seed() -> None:
    async with SessionLocal() as db:
        household = (await db.execute(select(Household).limit(1))).scalar_one_or_none()
        if household is None:
            household = Household(name="Home", timezone="America/Los_Angeles", currency="USD")
            db.add(household)
            await db.flush()

        await _upsert_user(
            db, household.id, ADMIN, UserRole.admin, totp_secret=DEV_ADMIN_TOTP_SECRET
        )
        kids = {
            child["username"]: await _upsert_user(db, household.id, child, UserRole.child)
            for child in CHILDREN
        }

        await _seed_chores(db, household.id, kids["alice"], kids["bea"])
        await db.commit()

    async with SessionLocal() as db:
        n_chores = len((await db.execute(select(Chore.id))).all())

    print("Seed complete.")
    print(f"  chores:   {n_chores}")
    print(f"  admin:    {ADMIN['username']} / {ADMIN['password']}")
    print(f"  admin TOTP secret: {DEV_ADMIN_TOTP_SECRET}")
    print(f"  admin TOTP now:    {pyotp.TOTP(DEV_ADMIN_TOTP_SECRET).now()}")
    for child in CHILDREN:
        print(f"  child:    {child['username']} / {child['password']}")


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
                prompt_token_enabled=True,
                verification_mode="llm_auto",
                verification_rule=(
                    "The sink basin is empty and the counters are clear of dirty dishes."
                ),
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
                verification_rule="The floor is clear, the bed is made, and clothes are put away.",
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


async def _upsert_user(db, household_id, spec, role: UserRole, *, totp_secret: str | None = None):
    existing = (
        await db.execute(select(User).where(User.username == spec["username"]))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    user = User(
        household_id=household_id,
        username=spec["username"],
        display_name=spec["display_name"],
        role=role,
        password_hash=hash_password(spec["password"]),
        totp_secret=totp_secret,
        totp_enrolled=totp_secret is not None,
    )
    db.add(user)
    await db.flush()
    return user


if __name__ == "__main__":
    asyncio.run(seed())
