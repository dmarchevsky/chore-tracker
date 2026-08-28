"""Development seed data (spec §13.3).

Phase 1: one household, one admin (TOTP pre-enrolled with a fixed dev secret), two
children. Phases 2/3 extend this with the four example chores and 30 days of backdated
occurrences in mixed states so the UI is never empty.

Run:  uv run python -m app.seed        (idempotent — safe to re-run)
"""

from __future__ import annotations

import asyncio

import pyotp
from sqlalchemy import select

from app.auth.passwords import hash_password
from app.db import SessionLocal
from app.models import Household, User, UserRole

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
        for child in CHILDREN:
            await _upsert_user(db, household.id, child, UserRole.child)

        await db.commit()

    print("Seed complete.")
    print(f"  admin:    {ADMIN['username']} / {ADMIN['password']}")
    print(f"  admin TOTP secret: {DEV_ADMIN_TOTP_SECRET}")
    print(f"  admin TOTP now:    {pyotp.TOTP(DEV_ADMIN_TOTP_SECRET).now()}")
    for child in CHILDREN:
        print(f"  child:    {child['username']} / {child['password']}")


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
