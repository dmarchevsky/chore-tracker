from __future__ import annotations

import os
import tempfile

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SESSION_SECRET", "test-secret")
os.environ.setdefault("MEDIA_ROOT", tempfile.mkdtemp(prefix="ck-media-"))

from app.auth import ratelimit
from app.auth.passwords import hash_password
from app.db import Base, get_session
from app.main import app
from app.models import Household, User, UserRole

ADMIN_BASE = "postgresql+asyncpg://chore:chore@localhost:5432/chore"
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://chore:chore@localhost:5432/chore_test"
)
TEST_TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


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
    user = User(
        household_id=household.id,
        username="parent",
        display_name="Parent",
        role=UserRole.admin,
        password_hash=hash_password("parent-pass"),
        totp_secret=TEST_TOTP_SECRET,
        totp_enrolled=True,
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def admin_no_totp(db_session, household) -> User:
    user = User(
        household_id=household.id,
        username="freshadmin",
        display_name="Fresh Admin",
        role=UserRole.admin,
        password_hash=hash_password("fresh-pass"),
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
        password_hash=hash_password("alice-pass"),
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest.fixture
def totp_now():
    import pyotp

    return lambda: pyotp.TOTP(TEST_TOTP_SECRET).now()
