"""Push TTL and per-device accounting (spec §4.5).

pywebpush defaults to ``ttl=0``, which tells the push service to deliver only if the device
is connected at that instant and otherwise discard the message — while still answering
success, so the send is recorded as `sent`. Every notification this app sent was thrown away
unless the phone happened to be awake; the on-demand test push worked every time because
someone was holding the phone. Nothing but the arguments at the call site proves it is fixed,
so these tests read them.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import NotificationLog, PushSubscription
from app.services import notifications

pytestmark = pytest.mark.asyncio


@pytest.fixture
def sends(monkeypatch) -> list[dict]:
    """Capture every webpush(**kwargs), with VAPID configured so the send path is reached."""
    calls: list[dict] = []

    def fake_webpush(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(notifications, "_vapid_ready", lambda: True)
    monkeypatch.setitem(__import__("sys").modules, "pywebpush", _module(fake_webpush))
    return calls


def _module(fn):
    import types

    m = types.ModuleType("pywebpush")
    m.webpush = fn
    return m


async def _subscribe(db, user, n: int = 1) -> None:
    for _ in range(n):
        db.add(
            PushSubscription(
                user_id=user.id,
                endpoint=f"https://push.example/{uuid.uuid4()}",
                p256dh="BPa" + "x" * 84,
                auth="y" * 22,
            )
        )
    await db.flush()


async def _row(db) -> NotificationLog:
    return (await db.execute(select(NotificationLog))).scalars().one()


async def test_a_miss_is_kept_for_a_day_not_discarded_on_a_sleeping_phone(
    db_session, admin_user, sends
):
    # The regression. ttl=0 is what shipped, and it is why a chore missed at 8:15am reached
    # nobody while the test button always worked.
    await _subscribe(db_session, admin_user)

    await notifications.notify(db_session, user_id=admin_user.id, kind="missed", title="x")

    assert sends[0]["ttl"] == 86400


@pytest.mark.parametrize(
    ("kind", "ttl"),
    [
        ("due_soon", 30 * 60),  # pointless once the chore is due
        ("window_open", 4 * 3600),
        ("test", 5 * 60),
        ("admin.needs_review", 86400),
        ("something.new", 86400),  # an unlisted kind must not fall back to 0
    ],
)
async def test_each_kind_carries_a_ttl_that_matches_how_long_it_stays_useful(
    db_session, admin_user, sends, kind, ttl
):
    await _subscribe(db_session, admin_user)

    await notifications.notify(db_session, user_id=admin_user.id, kind=kind, title="x")

    assert sends[0]["ttl"] == ttl


async def test_no_kind_is_ever_sent_with_a_zero_ttl():
    # A guard on the table itself: a 0 here would silently reinstate the original bug.
    assert notifications.DEFAULT_TTL_S > 0
    assert all(v > 0 for v in notifications._TTL_S.values())


async def test_a_clean_send_records_every_device(db_session, admin_user, sends):
    await _subscribe(db_session, admin_user, n=2)

    await notifications.notify(db_session, user_id=admin_user.id, kind="missed", title="x")

    row = await _row(db_session)
    assert (row.status, row.devices, row.delivered) == ("sent", 2, 2)


async def test_one_dead_device_no_longer_hides_behind_a_working_one(
    db_session, admin_user, monkeypatch
):
    # `sent` used to mean "at least one worked", so a phone that stopped receiving looked
    # identical to one that never missed a push.
    calls = {"n": 0}

    def flaky(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("gone")

    monkeypatch.setattr(notifications, "_vapid_ready", lambda: True)
    monkeypatch.setitem(__import__("sys").modules, "pywebpush", _module(flaky))
    await _subscribe(db_session, admin_user, n=2)

    await notifications.notify(db_session, user_id=admin_user.id, kind="missed", title="x")

    row = await _row(db_session)
    assert (row.status, row.devices, row.delivered) == ("partial", 2, 1)
    assert "gone" in row.error


async def test_every_device_failing_is_still_a_failure(db_session, admin_user, monkeypatch):
    def always_fails(**kwargs):
        raise RuntimeError("nope")

    monkeypatch.setattr(notifications, "_vapid_ready", lambda: True)
    monkeypatch.setitem(__import__("sys").modules, "pywebpush", _module(always_fails))
    await _subscribe(db_session, admin_user)

    await notifications.notify(db_session, user_id=admin_user.id, kind="missed", title="x")

    row = await _row(db_session)
    assert (row.status, row.devices, row.delivered) == ("failed", 1, 0)
