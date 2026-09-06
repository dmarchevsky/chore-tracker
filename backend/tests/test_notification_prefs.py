"""Per-user notification categories, and the parent's "a chore was done" push (spec §4.5).

VAPID is unset in tests, so a send that gets through is logged ``skipped`` — the distinction
that matters here is ``muted`` versus anything else, and the NotificationLog row is the whole
contract, exactly as in test_notification_events.py.
"""

from __future__ import annotations

import io
from datetime import UTC, date, datetime, time

import pytest
from PIL import Image
from sqlalchemy import select
from tests.helpers import sign_in

from app.models import Chore, ChoreOccurrence, NotificationLog, OccurrenceStatus
from app.services import notifications

pytestmark = pytest.mark.asyncio


async def _login(client, email: str) -> dict:
    r = await sign_in(client, email)
    return {"X-CSRF-Token": r.json()["csrf_token"]}


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (320, 240), (20, 120, 200)).save(buf, format="JPEG")
    return buf.getvalue()


async def _logs(db_session) -> list[NotificationLog]:
    return list((await db_session.execute(select(NotificationLog))).scalars().all())


async def test_each_role_is_offered_only_its_own_categories(client, admin_user, child_user):
    await _login(client, "parent@example.com")
    parent = (await client.get("/api/v1/push/settings")).json()
    assert parent["muted"] == []  # nothing is off until someone turns it off
    assert {c["key"] for c in parent["categories"]} == {
        "review",
        "completed",
        "misses",
        "disputes",
    }

    await _login(client, "alice@example.com")
    kid = (await client.get("/api/v1/push/settings")).json()
    assert {c["key"] for c in kid["categories"]} == {
        "chore_open",
        "due_soon",
        "results",
        "messages",
        "money_rules",
    }


async def test_muting_a_category_logs_the_send_instead_of_making_it(client, db_session, admin_user):
    h = await _login(client, "parent@example.com")
    r = await client.patch("/api/v1/push/settings", json={"muted": ["review"]}, headers=h)
    assert r.status_code == 200 and r.json()["muted"] == ["review"]

    await db_session.refresh(admin_user)
    await notifications.notify(
        db_session, user_id=admin_user.id, kind="admin.needs_review", title="x"
    )
    # A different category on the same account is untouched.
    await notifications.notify(db_session, user_id=admin_user.id, kind="admin.missed", title="y")

    by_kind = {log.kind: log.status for log in await _logs(db_session)}
    assert by_kind["admin.needs_review"] == "muted"
    assert by_kind["admin.missed"] == "skipped"


async def test_a_kid_cannot_mute_a_parents_category(client, child_user):
    h = await _login(client, "alice@example.com")
    r = await client.patch("/api/v1/push/settings", json={"muted": ["review"]}, headers=h)
    assert r.status_code == 422
    assert "review" in r.json()["detail"]


async def test_the_test_push_is_never_muted(client, db_session, admin_user):
    h = await _login(client, "parent@example.com")
    await client.patch(
        "/api/v1/push/settings",
        json={"muted": ["review", "completed", "misses", "disputes"]},
        headers=h,
    )

    r = await client.post("/api/v1/push/test", headers=h)

    # It is the diagnostic for whether any of this works; muting everything must not
    # silence the one send that answers "is my phone registered?".
    assert r.json()["status"] == "skipped"
    assert [x.status for x in await _logs(db_session) if x.kind == "test"] == ["skipped"]


async def test_an_uncategorised_kind_is_never_accidentally_muted(db_session, admin_user):
    admin_user.notification_mutes = ["review", "completed", "misses", "disputes"]
    await db_session.flush()

    await notifications.notify(db_session, user_id=admin_user.id, kind="something.new", title="x")

    assert [x.status for x in await _logs(db_session)] == ["skipped"]


async def test_an_auto_accepted_chore_tells_the_parents_it_was_done(
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
        verification_mode="auto_accept",
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

    kh = await _login(client, "alice@example.com")
    await client.post(
        f"/api/v1/occurrences/{occ.id}/submissions",
        files=[("files", ("a.jpg", _jpeg(), "image/jpeg"))],
        data={"source": "camera"},
        headers=kh,
    )

    logs = await _logs(db_session)
    completed = [x for x in logs if x.kind == "admin.completed"]
    assert len(completed) == 1 and completed[0].user_id == admin_user.id
    assert child_user.display_name in completed[0].body and "Kitchen" in completed[0].body
    # The kid still hears the verdict — the parent's category is a separate axis.
    assert any(x.kind.startswith("verdict.") and x.user_id == child_user.id for x in logs)


async def test_a_parents_own_approval_does_not_push_back_at_them(
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
        status=OccurrenceStatus.needs_review,
        reward_cents=200,
    )
    db_session.add(occ)
    await db_session.commit()

    ah = await _login(client, "parent@example.com")
    await client.post(
        f"/api/v1/occurrences/{occ.id}/decision",
        json={"action": "approve", "reason": "nice work"},
        headers=ah,
    )

    logs = await _logs(db_session)
    assert not [x for x in logs if x.kind == "admin.completed"]
    assert any(x.kind.startswith("verdict.") for x in logs)


async def test_muting_completed_leaves_the_kids_verdict_alone(
    client, db_session, household, admin_user, child_user
):
    h = await _login(client, "parent@example.com")
    await client.patch("/api/v1/push/settings", json={"muted": ["completed"]}, headers=h)

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
        verification_mode="auto_accept",
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

    kh = await _login(client, "alice@example.com")
    await client.post(
        f"/api/v1/occurrences/{occ.id}/submissions",
        files=[("files", ("a.jpg", _jpeg(), "image/jpeg"))],
        data={"source": "camera"},
        headers=kh,
    )

    logs = await _logs(db_session)
    assert [x.status for x in logs if x.kind == "admin.completed"] == ["muted"]
    assert [x.status for x in logs if x.kind.startswith("verdict.")] == ["skipped"]
