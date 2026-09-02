"""The dev seed (app/seed.py).

It writes demo chores, placeholder kids and a month of invented history, which is fine in a
development database and wrong in a household's real one. A production database is set up
by app/bootstrap.py instead — see test_bootstrap.py.
"""

from __future__ import annotations

import pytest

from app.auth.passwords import verify_password
from app.bootstrap import ensure_admin
from app.config import get_settings
from app.models import UserRole
from app.seed import DEV_ADMIN_PASSWORD, SeedRefused, _bootstrap_config


@pytest.fixture
def settings(monkeypatch):
    def _build(**env: str):
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()
        return get_settings()

    yield _build
    get_settings.cache_clear()


def test_prod_refuses_the_demo_data(settings):
    """The seed used to be the documented production bootstrap. It is not: a family's books
    should not open with invented chores and backdated occurrences in them."""
    with pytest.raises(SeedRefused, match="bootstrap"):
        _bootstrap_config(settings(ENVIRONMENT="prod", ADMIN_PASSWORD="a-long-enough-one"))


def test_dev_falls_back_to_the_dev_password(settings):
    cfg = _bootstrap_config(settings(ENVIRONMENT="dev", ADMIN_PASSWORD=""))
    assert cfg.password == DEV_ADMIN_PASSWORD


def test_an_explicit_password_still_wins_in_dev(settings):
    cfg = _bootstrap_config(settings(ENVIRONMENT="dev", ADMIN_PASSWORD="chosen-by-hand"))
    assert cfg.password == "chosen-by-hand"


async def test_the_seeded_admin_can_break_glass_with_that_password(db_session, settings):
    """End of the chain: what the seed hashes is what the break-glass login accepts."""
    cfg = _bootstrap_config(settings(ENVIRONMENT="dev", ADMIN_PASSWORD=""))
    admin, _ = await ensure_admin(db_session, cfg)
    await db_session.commit()

    assert admin.role == UserRole.admin
    assert verify_password(admin.password_hash, DEV_ADMIN_PASSWORD)
