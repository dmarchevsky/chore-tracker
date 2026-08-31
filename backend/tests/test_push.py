"""Phase 5: Web Push subscribe + notification logging (spec §4.5)."""

from __future__ import annotations

import io
from datetime import UTC, date, datetime, time

import pytest
from PIL import Image
from sqlalchemy import select

from app.models import (
    Chore,
    ChoreOccurrence,
    NotificationLog,
    OccurrenceStatus,
    PushSubscription,
)

pytestmark = pytest.mark.asyncio

SUB = {
    "endpoint": "https://push.example/abc123",
    "keys": {"p256dh": "BPa" + "x" * 84, "auth": "y" * 22},
}


async def _kid_login(client) -> dict:
    r = await client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "alice-pass"}
    )
    return {"X-CSRF-Token": r.json()["csrf_token"]}


async def _admin_login(client, totp_now) -> dict:
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "parent", "password": "parent-pass", "totp_code": totp_now()},
    )
    return {"X-CSRF-Token": r.json()["csrf_token"]}


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (320, 240), (20, 120, 200)).save(buf, format="JPEG")
    return buf.getvalue()


async def test_subscribe_and_resubscribe_is_idempotent(client, db_session, child_user):
    h = await _kid_login(client)
    assert (await client.post("/api/v1/push/subscribe", json=SUB, headers=h)).status_code == 204
    assert (await client.post("/api/v1/push/subscribe", json=SUB, headers=h)).status_code == 204

    rows = (await db_session.execute(select(PushSubscription))).scalars().all()
    assert len(rows) == 1 and rows[0].user_id == child_user.id


async def test_vapid_key_endpoint(client, child_user):
    # Unauthenticated callers are turned away (spec §12.1 endpoint inventory).
    assert (await client.get("/api/v1/push/vapid-key")).status_code == 401

    await _kid_login(client)
    r = await client.get("/api/v1/push/vapid-key")
    assert r.status_code == 200 and "public_key" in r.json()


async def test_verdict_logs_a_notification_even_without_vapid(
    client, db_session, household, admin_user, child_user, totp_now
):
    chore = Chore(
        household_id=household.id,
        title="Kitchen",
        assignment_mode="fixed",
        fixed_assignee_id=child_user.id,
        cadence="daily",
        due_time=time(8, 0),
        start_date=date(2025, 1, 1),
        proof_type="photo",
        photo_count=1,
        verification_mode="manual",
        reward_cents=200,
    )
    db_session.add(chore)
    await db_session.flush()
    occ = ChoreOccurrence(
        household_id=household.id,
        chore_id=chore.id,
        assignee_id=child_user.id,
        window_open_at=datetime(2025, 1, 2, tzinfo=UTC),
        due_at=datetime(2025, 1, 2, 16, tzinfo=UTC),
        status=OccurrenceStatus.open,
        reward_cents=200,
    )
    db_session.add(occ)
    await db_session.commit()

    kh = await _kid_login(client)
    await client.post(
        f"/api/v1/occurrences/{occ.id}/submissions",
        files=[("files", ("a.jpg", _jpeg(), "image/jpeg"))],
        data={"source": "camera"},
        headers=kh,
    )
    ah = await _admin_login(client, totp_now)
    await client.post(
        f"/api/v1/occurrences/{occ.id}/decision",
        json={"action": "approve", "reason": "great"},
        headers=ah,
    )

    logs = (await db_session.execute(select(NotificationLog))).scalars().all()
    kinds = {log.kind for log in logs}
    assert any(k.startswith("verdict.") for k in kinds)  # kid told
    assert "admin.needs_review" in kinds  # admin told at submit time
    assert all(log.status in ("skipped", "no_subs") for log in logs)  # no VAPID in tests


async def test_dispute_notifies_admins(
    client, db_session, household, admin_user, child_user, totp_now
):
    chore = Chore(
        household_id=household.id,
        title="Kitchen",
        assignment_mode="fixed",
        fixed_assignee_id=child_user.id,
        cadence="daily",
        due_time=time(8, 0),
        start_date=date(2025, 1, 1),
        proof_type="photo",
        verification_mode="manual",
        reward_cents=200,
    )
    db_session.add(chore)
    await db_session.flush()
    occ = ChoreOccurrence(
        household_id=household.id,
        chore_id=chore.id,
        assignee_id=child_user.id,
        window_open_at=datetime(2025, 1, 2, tzinfo=UTC),
        due_at=datetime(2025, 1, 2, 16, tzinfo=UTC),
        status=OccurrenceStatus.verified_fail,
        reward_cents=200,
    )
    db_session.add(occ)
    await db_session.commit()

    kh = await _kid_login(client)
    r = await client.post(
        f"/api/v1/occurrences/{occ.id}/dispute",
        json={"message": "the sink WAS empty!"},
        headers=kh,
    )
    assert r.status_code == 201  # the dispute row is created and returned
    logs = (await db_session.execute(select(NotificationLog))).scalars().all()
    assert any(log.kind == "admin.dispute" for log in logs)
