from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SESSION_SECRET", "test-secret")
os.environ.setdefault("MEDIA_ROOT", tempfile.mkdtemp(prefix="ck-media-"))

from app.auth import ratelimit
from app.auth.passwords import hash_password
from app.db import Base, get_session
from app.main import app
from app.models import Household, User, UserRole

DEFAULT_SERVER = "postgresql+asyncpg://chore:chore@localhost:5432/"


def _default_test_db_name() -> str:
    """A database per checkout, so worktrees running `just test` at once can't drop and
    truncate each other's tables — the `engine` fixture rebuilds the schema and `db_session`
    truncates every table, so a shared database means concurrent suites destroy each other.

    The directory name keeps it recognisable in `psql -l`; the path hash keeps two worktrees
    that happen to share a basename apart."""
    root = Path(__file__).resolve().parents[2]  # <worktree>/backend/tests/ -> <worktree>
    slug = re.sub(r"[^a-z0-9]+", "_", root.name.lower()).strip("_")[:30]
    digest = hashlib.sha1(str(root).encode()).hexdigest()[:8]
    return f"chore_test_{slug}_{digest}"  # <= 63 bytes, Postgres' identifier cap


# `str(URL)` masks the password as `***`, so render explicitly or nothing can connect.
TEST_DB_URL = os.environ.get("TEST_DATABASE_URL") or make_url(DEFAULT_SERVER).set(
    database=_default_test_db_name()
).render_as_string(hide_password=False)
# CREATE DATABASE has to run from another database on the same server — `postgres` is the
# maintenance one that is always there. Derived from TEST_DB_URL rather than hardcoded, so
# pointing TEST_DATABASE_URL at another host creates the database on that host.
ADMIN_BASE = make_url(TEST_DB_URL).set(database="postgres").render_as_string(hide_password=False)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _create_test_database():
    admin_engine = create_async_engine(ADMIN_BASE, isolation_level="AUTOCOMMIT")
    db_name = TEST_DB_URL.rsplit("/", 1)[-1]
    async with admin_engine.connect() as conn:
        exists = await conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": db_name}
        )
        if not exists:
            await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    await admin_engine.dispose()
    yield


@pytest_asyncio.fixture(scope="session")
async def engine(_create_test_database):
    eng = create_async_engine(TEST_DB_URL)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db_session(engine):
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        yield session
    # Clean every table after each test.
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(text(f'TRUNCATE TABLE "{table.name}" CASCADE'))
    ratelimit.reset()


@pytest_asyncio.fixture
async def client(engine, db_session):
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_session():
        async with sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def household(db_session) -> Household:
    hh = Household(name="Home", timezone="America/Los_Angeles", currency="USD")
    db_session.add(hh)
    await db_session.commit()
    return hh


@pytest_asyncio.fixture
async def admin_user(db_session, household) -> User:
    # The parent signs in with the Google address; the password is break-glass only.
    user = User(
        household_id=household.id,
        username="parent",
        display_name="Parent",
        role=UserRole.admin,
        email="parent@example.com",
        password_hash=hash_password("parent-pass"),
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def child_user(db_session, household) -> User:
    user = User(
        household_id=household.id,
        username="alice",
        display_name="Alice",
        role=UserRole.child,
        email="alice@example.com",
    )
    db_session.add(user)
    await db_session.commit()
    return user
