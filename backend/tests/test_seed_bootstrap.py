"""The seed is also the production bootstrap, so what password it plants matters (spec §12.1).

The dev literal is published in this repository and the LAN break-glass door offers that
login to every device on the home network, so seeding it into a production database would
hand out the admin account with the wifi password. These pin the refusal.
"""

from __future__ import annotations

import pytest

from app.auth.passwords import verify_password
from app.config import get_settings
from app.models import UserRole
from app.schemas.auth import BREAK_GLASS_MIN_LENGTH
from app.seed import (
    ADMIN,
    DEV_ADMIN_PASSWORD,
    SeedRefused,
    _admin_password,
    _upsert_user,
)


@pytest.fixture
def settings(monkeypatch):
    def _build(**env: str):
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()
        return get_settings()

    yield _build
    get_settings.cache_clear()


def test_dev_database_gets_the_dev_literal(settings):
    assert _admin_password(settings(ENVIRONMENT="dev")) == DEV_ADMIN_PASSWORD


def test_prod_without_admin_password_is_refused(settings):
    with pytest.raises(SeedRefused, match="ADMIN_PASSWORD"):
        _admin_password(settings(ENVIRONMENT="prod", ADMIN_PASSWORD=""))


def test_prod_rejects_a_password_the_api_would_reject(settings):
    short = "x" * (BREAK_GLASS_MIN_LENGTH - 1)
    with pytest.raises(SeedRefused, match=str(BREAK_GLASS_MIN_LENGTH)):
        _admin_password(settings(ENVIRONMENT="prod", ADMIN_PASSWORD=short))


def test_prod_accepts_an_operator_supplied_password(settings):
    chosen = "correct horse battery staple"
    assert _admin_password(settings(ENVIRONMENT="prod", ADMIN_PASSWORD=chosen)) == chosen


@pytest.mark.asyncio
async def test_the_seeded_admin_can_break_glass_with_the_supplied_password(
    db_session, household, settings
):
    """End of the chain: what the seed hashes is what the break-glass login will accept."""
    password = _admin_password(settings(ENVIRONMENT="prod", ADMIN_PASSWORD="a-long-enough-one"))
    admin = await _upsert_user(
        db_session, household.id, {**ADMIN, "password": password}, UserRole.admin
    )
    assert verify_password(admin.password_hash, "a-long-enough-one")
