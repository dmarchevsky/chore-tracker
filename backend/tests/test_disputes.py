"""Kid disputes land somewhere a parent can see and answer (spec §4.2, §6.3 rule 1)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.auth.passwords import hash_password
from app.config import get_settings
from app.models import Chore, ChoreOccurrence, Dispute, DisputeStatus, OccurrenceStatus, User
from app.models.user import UserRole

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def occ(db_session, household, child_user) -> ChoreOccurrence:
    """Due earlier today — inside the appeal window, which is measured from ``due_at``."""
    chore = Chore(
        household_id=household.id,
        title="Walk the dog",
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
    o = ChoreOccurrence(
        household_id=household.id,
        chore_id=chore.id,
        assignee_id=child_user.id,
        window_open_at=datetime.now(UTC) - timedelta(hours=6),
        due_at=datetime.now(UTC) - timedelta(hours=2),
        status=OccurrenceStatus.rejected,
        reward_cents=200,
    )
    db_session.add(o)
    await db_session.commit()
    return o


async def _kid_login(client, username="alice", password="alice-pass"):
    r = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    return {"X-CSRF-Token": r.json()["csrf_token"]}


async def _admin_login(client, totp_now):
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "parent", "password": "parent-pass", "totp_code": totp_now()},
    )
    return {"X-CSRF-Token": r.json()["csrf_token"]}


async def test_dispute_reaches_the_parent_and_the_reply_reaches_the_kid(
    client, db_session, occ, admin_user, child_user, totp_now
):
    kh = await _kid_login(client)
    filed = await client.post(
        f"/api/v1/occurrences/{occ.id}/dispute",
        json={"message": "I did walk him, the photo is just dark"},
        headers=kh,
    )
    assert filed.status_code == 201, filed.text
    assert filed.json()["status"] == "open"
    assert filed.json()["status_at_filing"] == "rejected"

    ah = await _admin_login(client, totp_now)
    listed = (await client.get("/api/v1/disputes", headers=ah)).json()
    assert [d["id"] for d in listed] == [filed.json()["id"]]
    assert listed[0]["chore_title"] == "Walk the dog"
    assert listed[0]["author_name"] == "Alice"

    resolved = await client.post(
        f"/api/v1/disputes/{filed.json()['id']}/resolve",
        json={"note": "You're right — approved it."},
        headers=ah,
    )
    assert resolved.status_code == 200
    assert (await client.get("/api/v1/disputes", headers=ah)).json() == []

    kh = await _kid_login(client)
    mine = (await client.get(f"/api/v1/occurrences/{occ.id}/disputes", headers=kh)).json()
    assert mine[0]["status"] == "resolved"
    assert mine[0]["resolution_note"] == "You're right — approved it."


async def test_only_one_open_dispute_per_occurrence(client, db_session, occ, child_user):
    kh = await _kid_login(client)
    first = await client.post(
        f"/api/v1/occurrences/{occ.id}/dispute", json={"message": "unfair"}, headers=kh
    )
    assert first.status_code == 201
    again = await client.post(
        f"/api/v1/occurrences/{occ.id}/dispute", json={"message": "still unfair"}, headers=kh
    )
    assert again.status_code == 409

    rows = (await db_session.execute(select(Dispute))).scalars().all()
    assert len(rows) == 1


async def test_a_kid_cannot_read_another_kids_dispute(client, db_session, occ, household):
    bob = User(
        household_id=household.id,
        username="bob",
        display_name="Bob",
        role=UserRole.child,
        password_hash=hash_password("bob-pass"),
    )
    db_session.add(bob)
    await db_session.commit()

    kh = await _kid_login(client)
    await client.post(f"/api/v1/occurrences/{occ.id}/dispute", json={"message": "hey"}, headers=kh)

    bh = await _kid_login(client, "bob", "bob-pass")
    r = await client.get(f"/api/v1/occurrences/{occ.id}/disputes", headers=bh)
    assert r.status_code == 404


async def test_resolving_twice_is_a_conflict(client, db_session, occ, admin_user, totp_now):
    kh = await _kid_login(client)
    d = (
        await client.post(
            f"/api/v1/occurrences/{occ.id}/dispute", json={"message": "unfair"}, headers=kh
        )
    ).json()

    ah = await _admin_login(client, totp_now)
    body = {"note": "had a look"}
    assert (
        await client.post(f"/api/v1/disputes/{d['id']}/resolve", json=body, headers=ah)
    ).status_code == 200
    again = await client.post(f"/api/v1/disputes/{d['id']}/resolve", json=body, headers=ah)
    assert again.status_code == 409

    row = await db_session.get(Dispute, d["id"])
    assert row.status == DisputeStatus.resolved


async def test_an_appeal_filed_too_late_is_refused(client, db_session, occ, child_user):
    """The window closes so a settled week can stay settled; a parent still has excuse."""
    occ.due_at = datetime.now(UTC) - timedelta(seconds=get_settings().appeal_window_s + 60)
    await db_session.commit()

    kh = await _kid_login(client)
    r = await client.post(
        f"/api/v1/occurrences/{occ.id}/dispute", json={"message": "much too late"}, headers=kh
    )
    assert r.status_code == 409
    assert "too late" in r.json()["detail"]
    assert (await db_session.execute(select(Dispute))).scalars().first() is None
