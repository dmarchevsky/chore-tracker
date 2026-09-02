"""Phase 5: admin ops dashboard + occurrence submissions listing (spec §10)."""

from __future__ import annotations

import io
from datetime import UTC, date, datetime, time

import pytest
from PIL import Image
from tests.helpers import sign_in

from app.models import Chore, ChoreOccurrence, OccurrenceStatus

pytestmark = pytest.mark.asyncio


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (320, 240), (10, 90, 160)).save(buf, format="JPEG")
    return buf.getvalue()


async def _admin(client) -> dict:
    r = await sign_in(client, "parent@example.com")
    return {"X-CSRF-Token": r.json()["csrf_token"]}


async def test_admin_jobs_requires_admin(client, child_user):
    await sign_in(client, "alice@example.com")
    assert (await client.get("/api/v1/admin/jobs")).status_code == 403


async def test_admin_jobs_shape(client, admin_user, child_user):
    h = await _admin(client)
    # mint a check-in token so the dashboard has a row
    await client.get(f"/api/v1/children/{child_user.id}/checkin-token", headers=h)

    r = await client.get("/api/v1/admin/jobs", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"queue", "stuck_jobs", "scheduler", "recent_failures", "checkins"}
    assert body["checkins"] and body["checkins"][0]["stale"] is True


async def test_occurrence_submissions_returns_signed_media(
    client, db_session, household, admin_user, child_user
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

    login = await sign_in(client, "alice@example.com")
    await client.post(
        f"/api/v1/occurrences/{occ.id}/submissions",
        files=[("files", ("a.jpg", _jpeg(), "image/jpeg"))],
        data={"source": "camera"},
        headers={"X-CSRF-Token": login.json()["csrf_token"]},
    )

    h = await _admin(client)
    r = await client.get(f"/api/v1/occurrences/{occ.id}/submissions", headers=h)
    assert r.status_code == 200
    subs = r.json()
    assert len(subs) == 1
    assert subs[0]["media"][0]["url"].startswith(f"/api/v1/submissions/{subs[0]['id']}/media/0?")

    # and the signed URL actually serves bytes with no session
    client.cookies.clear()
    media = await client.get(subs[0]["media"][0]["url"])
    assert media.status_code == 200 and media.headers["content-type"] == "image/jpeg"


# --- scheduler liveness (implementation-plan Phase 6 items 6, 8) -----------------------


async def test_a_worker_that_has_never_ticked_reads_as_stale(client, admin_user):
    """The failure this exists for is silent: no worker means no chores generated, no misses
    detected and no money settled, while every screen still renders."""
    h = await _admin(client)
    body = (await client.get("/api/v1/admin/jobs", headers=h)).json()
    assert body["scheduler"] == {"last_tick_at": None, "stale": True}


async def test_a_recent_tick_reads_as_live(client, db_session, admin_user, household):
    from app.services.heartbeat import record_tick

    await record_tick(db_session)
    await db_session.commit()

    h = await _admin(client)
    body = (await client.get("/api/v1/admin/jobs", headers=h)).json()
    assert body["scheduler"]["stale"] is False
    assert body["scheduler"]["last_tick_at"] is not None


async def test_an_old_tick_reads_as_stale(client, db_session, admin_user, household):
    from datetime import timedelta

    from app.services.heartbeat import STALE_AFTER_S, record_tick

    await record_tick(db_session, now=datetime.now(UTC) - timedelta(seconds=STALE_AFTER_S + 60))
    await db_session.commit()

    h = await _admin(client)
    assert (await client.get("/api/v1/admin/jobs", headers=h)).json()["scheduler"]["stale"] is True


async def test_recording_a_tick_before_the_household_exists_is_a_no_op(db_session):
    """A fresh production volume has no household until the bootstrap seed runs, and the
    worker ticks throughout — it must not raise there."""
    from sqlalchemy import delete

    from app.models import Household, HouseholdSettings
    from app.services.heartbeat import last_tick, record_tick

    await db_session.execute(delete(HouseholdSettings))
    await db_session.execute(delete(Household))
    await db_session.commit()

    await record_tick(db_session)
    await db_session.commit()
    assert await last_tick(db_session) is None
