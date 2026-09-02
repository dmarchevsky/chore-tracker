"""First-run bootstrap (app/bootstrap.py).

A brand-new database has no household and no users, and until one exists neither door opens
— Access vouches for an address matching no row, and break-glass has no account to check a
password against. This is the module that fixes that, and these pin the two properties that
make it safe to point at a family's real database: it creates the admin, and it creates
*nothing else*.
"""

from __future__ import annotations

import sys

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from tests.helpers import sign_in

from app import bootstrap as bootstrap_mod
from app.bootstrap import (
    BootstrapRefused,
    config_from_env,
    ensure_admin,
    main,
    run,
    users_exist,
)
from app.config import get_settings
from app.models import (
    Chore,
    ChoreOccurrence,
    Household,
    HouseholdSettings,
    LedgerEntry,
    User,
    UserRole,
)
from app.schemas.auth import BREAK_GLASS_MIN_LENGTH

EMAIL = "parent@example.com"
PASSWORD = "a-long-enough-password"


@pytest.fixture
def env(monkeypatch):
    def _set(**values: str):
        for key, value in values.items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()
        return get_settings()

    yield _set
    get_settings.cache_clear()


@pytest.fixture
def on_test_db(engine, monkeypatch):
    """Point ``run()``/``main()`` at the test database.

    They open their own session through ``app.db.SessionLocal``, which conftest never
    rebinds — so without this they would talk to whatever ``DATABASE_URL`` names, i.e. the
    developer's dev database, and a bootstrap that found it empty would write an admin into
    it.
    """
    monkeypatch.setattr(
        bootstrap_mod, "SessionLocal", async_sessionmaker(engine, expire_on_commit=False)
    )


@pytest.fixture
async def empty_db(db_session):
    """A database as a fresh deployment finds it: no household, no users, nothing."""
    await db_session.execute(delete(HouseholdSettings))
    await db_session.execute(delete(User))
    await db_session.execute(delete(Household))
    await db_session.commit()
    return db_session


async def _count(db, model) -> int:
    return await db.scalar(select(func.count()).select_from(model)) or 0


async def test_creates_the_household_and_one_admin(empty_db, env):
    cfg = config_from_env(env(ENVIRONMENT="prod", ADMIN_EMAIL=EMAIL, ADMIN_PASSWORD=PASSWORD))
    admin, created = await ensure_admin(empty_db, cfg)
    await empty_db.commit()

    assert created is True
    assert admin.role == UserRole.admin
    assert admin.email == EMAIL
    assert admin.is_active is True
    assert await _count(empty_db, Household) == 1
    assert await _count(empty_db, User) == 1


async def test_creates_no_demo_data(empty_db, env):
    """The reason this is a separate module from the seed: it is safe on the real books."""
    cfg = config_from_env(env(ENVIRONMENT="prod", ADMIN_EMAIL=EMAIL, ADMIN_PASSWORD=PASSWORD))
    await ensure_admin(empty_db, cfg)
    await empty_db.commit()

    assert await _count(empty_db, Chore) == 0
    assert await _count(empty_db, ChoreOccurrence) == 0
    assert await _count(empty_db, LedgerEntry) == 0


async def test_both_doors_open_afterwards(client, empty_db, env):
    """The bug this closes: Access said 'not an active member' and break-glass said
    'invalid credentials', because nothing had ever created a row for either to match."""
    cfg = config_from_env(env(ENVIRONMENT="dev", ADMIN_EMAIL=EMAIL, ADMIN_PASSWORD=PASSWORD))
    await ensure_admin(empty_db, cfg)
    await empty_db.commit()

    assert (await sign_in(client, EMAIL)).status_code == 200

    r = await client.post("/api/v1/auth/login", json={"username": "parent", "password": PASSWORD})
    assert r.status_code == 200


async def test_a_rerun_repoints_the_admin_and_adds_no_second_user(empty_db, env):
    """The recovery path for a typo'd ADMIN_EMAIL — otherwise it is SQL on the host, because
    a parent cannot reach the app to correct it."""
    first = config_from_env(env(ENVIRONMENT="prod", ADMIN_EMAIL=EMAIL, ADMIN_PASSWORD=PASSWORD))
    await ensure_admin(empty_db, first)
    await empty_db.commit()

    second = config_from_env(
        env(ENVIRONMENT="prod", ADMIN_EMAIL="corrected@example.com", ADMIN_PASSWORD=PASSWORD)
    )
    admin, created = await ensure_admin(empty_db, second)
    await empty_db.commit()

    assert created is False
    assert admin.email == "corrected@example.com"
    assert await _count(empty_db, User) == 1


async def test_rerun_reactivates_a_disabled_admin(empty_db, env):
    cfg = config_from_env(env(ENVIRONMENT="prod", ADMIN_EMAIL=EMAIL, ADMIN_PASSWORD=PASSWORD))
    admin, _ = await ensure_admin(empty_db, cfg)
    admin.is_active = False
    await empty_db.commit()

    admin, _ = await ensure_admin(empty_db, cfg)
    await empty_db.commit()
    assert admin.is_active is True


# --- refusals (spec §12.1) -------------------------------------------------------------


async def test_prod_refuses_without_an_admin_email(env):
    with pytest.raises(BootstrapRefused, match="ADMIN_EMAIL"):
        config_from_env(env(ENVIRONMENT="prod", ADMIN_EMAIL="", ADMIN_PASSWORD=PASSWORD))


async def test_prod_refuses_without_a_password(env):
    with pytest.raises(BootstrapRefused, match="ADMIN_PASSWORD"):
        config_from_env(env(ENVIRONMENT="prod", ADMIN_EMAIL=EMAIL, ADMIN_PASSWORD=""))


async def test_refuses_a_password_the_api_would_reject(env):
    with pytest.raises(BootstrapRefused, match=str(BREAK_GLASS_MIN_LENGTH)):
        config_from_env(env(ENVIRONMENT="prod", ADMIN_EMAIL=EMAIL, ADMIN_PASSWORD="x" * 4))


# --- --if-empty, which the api container runs on every start ----------------------------


async def test_if_empty_is_a_no_op_once_a_user_exists(db_session, admin_user, env, on_test_db):
    env(ENVIRONMENT="prod", ADMIN_EMAIL="someone-else@example.com", ADMIN_PASSWORD=PASSWORD)
    assert await users_exist(db_session) is True

    before = admin_user.email
    assert "nothing to do" in await run(if_empty=True)

    await db_session.refresh(admin_user)
    assert admin_user.email == before


def test_if_empty_lets_an_unconfigured_stack_boot(env, monkeypatch, capsys, on_test_db):
    """It runs before uvicorn on every start, so an incomplete environment has to mean
    'not set up for automatic bootstrap', not 'this stack does not come up'."""
    env(ENVIRONMENT="prod", ADMIN_EMAIL="", ADMIN_PASSWORD="")
    monkeypatch.setattr(sys, "argv", ["app.bootstrap", "--if-empty"])

    main()  # must not raise SystemExit

    assert "skipped" in capsys.readouterr().out


def test_without_if_empty_a_refusal_is_an_error(env, monkeypatch, on_test_db):
    """Run by hand, the same misconfiguration has to be loud — the operator is standing
    there waiting to be told why they still cannot sign in."""
    env(ENVIRONMENT="prod", ADMIN_EMAIL="", ADMIN_PASSWORD="")
    monkeypatch.setattr(sys, "argv", ["app.bootstrap"])

    with pytest.raises(SystemExit, match="ADMIN_EMAIL"):
        main()
