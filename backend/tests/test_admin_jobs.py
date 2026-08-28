"""Phase 5: admin ops dashboard + occurrence submissions listing (spec §10)."""

from __future__ import annotations

import io
from datetime import UTC, date, datetime, time

import pytest
from PIL import Image

from app.models import Chore, ChoreOccurrence, OccurrenceStatus

pytestmark = pytest.mark.asyncio


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (320, 240), (10, 90, 160)).save(buf, format="JPEG")
    return buf.getvalue()


async def _admin(client, totp_now) -> dict:
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "parent", "password": "parent-pass", "totp_code": totp_now()},
    )
    return {"X-CSRF-Token": r.json()["csrf_token"]}


async def test_admin_jobs_requires_admin(client, child_user):
    await client.post("/api/v1/auth/login", json={"username": "alice", "password": "alice-pass"})
    assert (await client.get("/api/v1/admin/jobs")).status_code == 403


async def test_admin_jobs_shape(client, admin_user, child_user, totp_now):
    h = await _admin(client, totp_now)
    # mint a check-in token so the dashboard has a row
    await client.get(f"/api/v1/children/{child_user.id}/checkin-token", headers=h)

    r = await client.get("/api/v1/admin/jobs", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"queue", "stuck_jobs", "recent_failures", "checkins"}
    assert body["checkins"] and body["checkins"][0]["stale"] is True


async def test_occurrence_submissions_returns_signed_media(
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

    login = await client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "alice-pass"}
    )
    await client.post(
        f"/api/v1/occurrences/{occ.id}/submissions",
        files=[("files", ("a.jpg", _jpeg(), "image/jpeg"))],
        data={"source": "camera"},
        headers={"X-CSRF-Token": login.json()["csrf_token"]},
    )

    h = await _admin(client, totp_now)
    r = await client.get(f"/api/v1/occurrences/{occ.id}/submissions", headers=h)
    assert r.status_code == 200
    subs = r.json()
    assert len(subs) == 1
    assert subs[0]["media"][0]["url"].startswith(f"/api/v1/submissions/{subs[0]['id']}/media/0?")

    # and the signed URL actually serves bytes with no session
    client.cookies.clear()
    media = await client.get(subs[0]["media"][0]["url"])
    assert media.status_code == 200 and media.headers["content-type"] == "image/jpeg"
