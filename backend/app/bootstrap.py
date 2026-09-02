"""First-run bootstrap: create the household and the parent-admin, and nothing else.

A brand-new database has no household and no users, and until one exists **neither door
opens**: Cloudflare Access vouches for a Google address that matches no row, and the LAN
break-glass login has no account to check a password against. Nothing else in this codebase
creates those rows — ``app/seed.py`` did, but it also writes demo chores, kids and a month
of backdated occurrences, which is not something to run against a family's real database.

So this is the missing step, and it is deliberately the *whole* step: one household, one
admin, no chores, no kids, no occurrences, no ledger entries.

    python -m app.bootstrap              create or re-point the admin from the environment
    python -m app.bootstrap --if-empty   ...but do nothing at all if any user already exists

``--if-empty`` is what the api container runs after ``alembic upgrade head``, so a fresh
deployment comes up signed-in-able with no shell access. It is a silent no-op on a populated
database or with the environment unset — it must never be the reason a stack fails to boot.

A plain re-run **re-points the existing admin** at the current ``ADMIN_EMAIL`` and
``ADMIN_PASSWORD``. That is the recovery path for the address being wrong: without it the
only fix is SQL on the host, because no endpoint can change an admin's own email until they
can sign in to use it (spec §12.1).
"""

from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import hash_password
from app.config import Settings, get_settings
from app.db import SessionLocal
from app.models import Household, User, UserRole
from app.schemas.auth import BREAK_GLASS_MIN_LENGTH
from app.services import audit

ADMIN_USERNAME = "parent"
ADMIN_DISPLAY_NAME = "Parent"
DEFAULT_HOUSEHOLD_NAME = "Home"


class BootstrapRefused(RuntimeError):
    """The environment does not describe an admin this database should be given."""


@dataclass(frozen=True)
class BootstrapConfig:
    email: str
    password: str
    household_name: str
    timezone: str


def config_from_env(settings: Settings | None = None) -> BootstrapConfig:
    """Read and check the bootstrap inputs.

    Both credentials are required on a production database. The password is held to the same
    minimum the API enforces when a parent changes it later, so the bootstrap cannot install
    something the app would reject.
    """
    s = settings or get_settings()
    email = (s.admin_email or "").strip().lower()
    password = s.admin_password

    if s.is_prod:
        if not email:
            raise BootstrapRefused(
                "ADMIN_EMAIL is not set. That is the Google address Cloudflare Access will "
                "present, and without a user carrying it the app turns you away at sign-in."
            )
        if not password:
            raise BootstrapRefused(
                "ADMIN_PASSWORD is not set. It is the break-glass password, the way back in "
                "when Cloudflare or Google is unavailable."
            )
    if password and len(password) < BREAK_GLASS_MIN_LENGTH:
        raise BootstrapRefused(
            f"ADMIN_PASSWORD is shorter than the {BREAK_GLASS_MIN_LENGTH}-character minimum "
            "the API enforces on this same password (spec §12.1)."
        )
    return BootstrapConfig(
        email=email,
        password=password,
        household_name=os.environ.get("HOUSEHOLD_NAME", "").strip() or DEFAULT_HOUSEHOLD_NAME,
        timezone=s.tz,
    )


async def ensure_household(db: AsyncSession, cfg: BootstrapConfig) -> Household:
    """The single household (spec §1: tenancy is one row in v1)."""
    household = (await db.execute(select(Household).limit(1))).scalar_one_or_none()
    if household is None:
        household = Household(name=cfg.household_name, timezone=cfg.timezone, currency="USD")
        db.add(household)
        await db.flush()
    return household


async def ensure_admin(db: AsyncSession, cfg: BootstrapConfig) -> tuple[User, bool]:
    """Create the parent-admin, or re-point the existing one. Returns ``(user, created)``.

    Re-pointing is the whole recovery story for a wrong ``ADMIN_EMAIL``, so it updates
    rather than skipping — but only the two fields it is given, never the rest of the row.
    """
    household = await ensure_household(db, cfg)
    admin = (
        (
            await db.execute(
                select(User).where(User.role == UserRole.admin).order_by(User.created_at)
            )
        )
        .scalars()
        .first()
    )

    created = admin is None
    if admin is None:
        admin = User(
            household_id=household.id,
            username=ADMIN_USERNAME,
            display_name=ADMIN_DISPLAY_NAME,
            role=UserRole.admin,
        )
        db.add(admin)

    before = {"email": admin.email, "is_active": admin.is_active} if not created else None
    if cfg.email:
        admin.email = cfg.email
    if cfg.password:
        admin.password_hash = hash_password(cfg.password)
    # A deactivated admin cannot sign in, and this command exists to make signing in
    # possible; leaving it off would be a bootstrap that silently did not work.
    admin.is_active = True
    await db.flush()

    await audit.record(
        db,
        action="household.bootstrap" if created else "household.bootstrap.repoint",
        entity_type="user",
        entity_id=admin.id,
        actor_kind="system",
        before=before,
        after={"username": admin.username, "email": admin.email},
    )
    return admin, created


async def users_exist(db: AsyncSession) -> bool:
    return bool(await db.scalar(select(func.count()).select_from(User)))


async def run(*, if_empty: bool = False) -> str:
    """Do the work in one transaction. Returns a line describing what happened.

    The environment is read first, before any connection: an unconfigured stack is the
    common ``--if-empty`` case on every restart, and it should not need the database to
    decide it has nothing to do.
    """
    cfg = config_from_env()
    async with SessionLocal() as db:
        if if_empty and await users_exist(db):
            return "bootstrap: users already exist, nothing to do"
        admin, created = await ensure_admin(db, cfg)
        await db.commit()
        verb = "created" if created else "re-pointed"
        return f"bootstrap: {verb} admin {admin.username!r} <{admin.email or 'no address'}>"


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the household and the parent-admin.")
    parser.add_argument(
        "--if-empty",
        action="store_true",
        help="do nothing if any user already exists, and never fail the caller",
    )
    args = parser.parse_args()

    try:
        print(asyncio.run(run(if_empty=args.if_empty)))
    except BootstrapRefused as exc:
        if args.if_empty:
            # The api container runs this on every start. An incomplete environment means
            # "not configured for automatic bootstrap", which is a normal state — say so and
            # let the app start, rather than holding the whole stack down.
            print(f"bootstrap: skipped — {exc}")
            return
        raise SystemExit(f"bootstrap refused: {exc}") from exc


if __name__ == "__main__":
    main()
