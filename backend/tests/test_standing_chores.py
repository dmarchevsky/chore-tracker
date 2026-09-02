"""Standing chores: a state a parent flips, not a schedule (spec §4.7)."""

from __future__ import annotations

import uuid as uuidlib

import pytest
from sqlalchemy import func, select
from tests.helpers import sign_in

from app.models import (
    AuditLog,
    ChoreOccurrence,
    ChoreStateEvent,
    NotificationLog,
    User,
    UserRole,
)
from app.services.cadence import cadence_dates
from app.services.scheduler import reconcile

pytestmark = pytest.mark.asyncio

GROUNDED = [
    {
        "id": 1,
        "condition": "more than one missing assignment",
        "outcome_kind": "text",
        "text": "grounded until it's fixed",
    },
    {
        "id": 2,
        "condition": "missed a test",
        "outcome_kind": "text",
        "text": "no screens after 6pm",
    },
]


async def _admin_headers(client) -> dict:
    r = await sign_in(client, "parent@example.com")
    return {"X-CSRF-Token": r.json()["csrf_token"]}


async def _kid_headers(client) -> dict:
    r = await sign_in(client, "alice@example.com")
    return {"X-CSRF-Token": r.json()["csrf_token"]}


def _standing_body(child, **over) -> dict:
    body = {
        "chore_kind": "standing",
        "title": "Missing assignments",
        "assignment_mode": "fixed",
        "fixed_assignee_id": str(child.id),
        "outcome_tiers": GROUNDED,
    }
    body.update(over)
    return body


async def _mk(client, headers, child, **over) -> dict:
    r = await client.post("/api/v1/chores", json=_standing_body(child, **over), headers=headers)
    assert r.status_code == 201, r.json()
    return r.json()


# --------------------------------------------------------------- definition


async def test_standing_chore_needs_no_schedule_or_proof_fields(client, admin_user, child_user):
    """A parent never sees cadence/due_time/proof for a standing chore, so the API must not
    demand them — the before-validator fills the NOT NULL columns."""
    h = await _admin_headers(client)
    body = await _mk(client, h, child_user)

    assert body["chore_kind"] == "standing"
    assert body["cadence"] == "standing"
    assert body["proof_type"] == "none"
    assert body["verification_mode"] == "manual"
    assert body["standing_on"] is False
    assert body["standing_since"] is None


async def test_standing_cadence_token_never_fires(client, admin_user):
    from datetime import date

    assert cadence_dates("standing", date(2020, 1, 1), date(2030, 1, 1)) == []


async def test_scheduler_makes_no_occurrences_for_a_standing_chore(
    client, db_session, admin_user, child_user
):
    h = await _admin_headers(client)
    body = await _mk(client, h, child_user)
    await reconcile(db_session)

    n = await db_session.scalar(
        select(func.count())
        .select_from(ChoreOccurrence)
        .where(ChoreOccurrence.chore_id == uuidlib.UUID(body["id"]))
    )
    assert n == 0


async def test_standing_chore_rejects_money(client, admin_user, child_user):
    h = await _admin_headers(client)
    for over in ({"reward_cents": 100}, {"penalty_cents": 100}):
        r = await client.post("/api/v1/chores", json=_standing_body(child_user, **over), headers=h)
        assert r.status_code == 422, over
        assert "writes no ledger entries" in str(r.json())


async def test_standing_chore_rejects_a_money_tier(client, admin_user, child_user):
    h = await _admin_headers(client)
    tiers = [{"id": 1, "condition": "x", "outcome_kind": "money", "amount_cents": 500}]
    r = await client.post(
        "/api/v1/chores", json=_standing_body(child_user, outcome_tiers=tiers), headers=h
    )
    assert r.status_code == 422
    assert "text only" in str(r.json())


async def test_standing_chore_needs_an_outcome(client, admin_user, child_user):
    h = await _admin_headers(client)
    r = await client.post(
        "/api/v1/chores", json=_standing_body(child_user, outcome_tiers=None), headers=h
    )
    assert r.status_code == 422
    assert "at least one condition" in str(r.json())


async def test_standing_chore_rejects_rotation_and_proof(client, admin_user, child_user):
    h = await _admin_headers(client)
    r = await client.post(
        "/api/v1/chores",
        json=_standing_body(child_user, assignment_mode="anyone", fixed_assignee_id=None),
        headers=h,
    )
    assert r.status_code == 422
    assert "fixed or to all" in str(r.json())

    r = await client.post(
        "/api/v1/chores", json=_standing_body(child_user, proof_type="photo"), headers=h
    )
    assert r.status_code == 422
    assert "takes no proof" in str(r.json())


async def test_standing_chore_rejects_an_end_date(client, admin_user, child_user):
    h = await _admin_headers(client)
    r = await client.post(
        "/api/v1/chores", json=_standing_body(child_user, end_date="2030-01-01"), headers=h
    )
    assert r.status_code == 422
    assert "no end_date" in str(r.json())


# --------------------------------------------------------------- flipping


async def test_toggle_on_records_the_state_and_an_event(client, db_session, admin_user, child_user):
    h = await _admin_headers(client)
    body = await _mk(client, h, child_user)

    r = await client.post(
        f"/api/v1/chores/{body['id']}/state",
        json={"on": True, "tier_id": 1, "note": "two missing in maths"},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["standing_on"] is True
    assert r.json()["standing_tier_id"] == 1
    assert r.json()["standing_since"] is not None

    ev = (
        await db_session.execute(
            select(ChoreStateEvent).where(ChoreStateEvent.chore_id == uuidlib.UUID(body["id"]))
        )
    ).scalar_one()
    assert ev.state is True
    assert ev.tier["text"] == "grounded until it's fixed"  # snapshot, not a live lookup
    assert ev.note == "two missing in maths"
    assert ev.actor_user_id == admin_user.id


async def test_toggling_on_twice_is_idempotent(client, db_session, admin_user, child_user):
    h = await _admin_headers(client)
    body = await _mk(client, h, child_user)

    for _ in range(2):
        assert (
            await client.post(
                f"/api/v1/chores/{body['id']}/state", json={"on": True, "tier_id": 1}, headers=h
            )
        ).status_code == 200

    n = await db_session.scalar(
        select(func.count())
        .select_from(ChoreStateEvent)
        .where(ChoreStateEvent.chore_id == uuidlib.UUID(body["id"]))
    )
    assert n == 1


async def test_changing_the_tier_while_on_records_a_new_event(
    client, db_session, admin_user, child_user
):
    h = await _admin_headers(client)
    body = await _mk(client, h, child_user)

    await client.post(
        f"/api/v1/chores/{body['id']}/state", json={"on": True, "tier_id": 1}, headers=h
    )
    r = await client.post(
        f"/api/v1/chores/{body['id']}/state", json={"on": True, "tier_id": 2}, headers=h
    )
    assert r.status_code == 200
    assert r.json()["standing_tier_id"] == 2

    n = await db_session.scalar(
        select(func.count())
        .select_from(ChoreStateEvent)
        .where(ChoreStateEvent.chore_id == uuidlib.UUID(body["id"]))
    )
    assert n == 2


async def test_toggle_off_clears_the_tier_and_since(client, admin_user, child_user):
    h = await _admin_headers(client)
    body = await _mk(client, h, child_user)

    await client.post(
        f"/api/v1/chores/{body['id']}/state", json={"on": True, "tier_id": 1}, headers=h
    )
    r = await client.post(f"/api/v1/chores/{body['id']}/state", json={"on": False}, headers=h)
    assert r.status_code == 200
    assert r.json()["standing_on"] is False
    assert r.json()["standing_tier_id"] is None
    assert r.json()["standing_since"] is None


async def test_turning_on_needs_a_tier_and_off_takes_none(client, admin_user, child_user):
    h = await _admin_headers(client)
    body = await _mk(client, h, child_user)

    r = await client.post(f"/api/v1/chores/{body['id']}/state", json={"on": True}, headers=h)
    assert r.status_code == 409
    assert "needs the outcome that applies" in r.json()["detail"]

    r = await client.post(
        f"/api/v1/chores/{body['id']}/state", json={"on": False, "tier_id": 1}, headers=h
    )
    assert r.status_code == 409


async def test_unknown_tier_is_rejected(client, admin_user, child_user):
    h = await _admin_headers(client)
    body = await _mk(client, h, child_user)

    r = await client.post(
        f"/api/v1/chores/{body['id']}/state", json={"on": True, "tier_id": 9}, headers=h
    )
    assert r.status_code == 409
    assert "not one of this chore's outcomes" in r.json()["detail"]


async def test_flipping_a_scheduled_chore_is_refused(client, admin_user, child_user):
    h = await _admin_headers(client)
    created = await client.post(
        "/api/v1/chores",
        json={
            "title": "Dishes",
            "assignment_mode": "fixed",
            "fixed_assignee_id": str(child_user.id),
            "cadence": "daily",
            "due_time": "08:00:00",
            "start_date": "2025-01-01",
            "proof_type": "photo",
            "verification_mode": "manual",
            "reward_cents": 100,
        },
        headers=h,
    )
    r = await client.post(
        f"/api/v1/chores/{created.json()['id']}/state",
        json={"on": True, "tier_id": 1},
        headers=h,
    )
    assert r.status_code == 409
    assert "only a standing chore" in r.json()["detail"]


async def test_flipping_is_admin_only(client, admin_user, child_user):
    h = await _admin_headers(client)
    body = await _mk(client, h, child_user)

    kh = await _kid_headers(client)
    r = await client.post(
        f"/api/v1/chores/{body['id']}/state", json={"on": True, "tier_id": 1}, headers=kh
    )
    assert r.status_code == 403


async def test_flip_writes_an_audit_row(client, db_session, admin_user, child_user):
    h = await _admin_headers(client)
    body = await _mk(client, h, child_user)
    await client.post(
        f"/api/v1/chores/{body['id']}/state", json={"on": True, "tier_id": 1}, headers=h
    )

    n = await db_session.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == "chore.standing.on")
    )
    assert n == 1


# --------------------------------------------------------------- visibility


async def test_history_is_newest_first_and_a_kid_can_read_it(client, admin_user, child_user):
    h = await _admin_headers(client)
    body = await _mk(client, h, child_user)
    await client.post(
        f"/api/v1/chores/{body['id']}/state", json={"on": True, "tier_id": 1}, headers=h
    )
    await client.post(f"/api/v1/chores/{body['id']}/state", json={"on": False}, headers=h)

    await _kid_headers(client)
    r = await client.get(f"/api/v1/chores/{body['id']}/state/history")
    assert r.status_code == 200
    assert [e["state"] for e in r.json()] == [False, True]


async def test_a_kid_sees_the_live_state_on_the_chore_list(client, admin_user, child_user):
    """No new kid endpoint: GET /chores already serves definitions to children (spec §15 Q8)."""
    h = await _admin_headers(client)
    body = await _mk(client, h, child_user)
    await client.post(
        f"/api/v1/chores/{body['id']}/state", json={"on": True, "tier_id": 1}, headers=h
    )

    await _kid_headers(client)
    listed = (await client.get("/api/v1/chores")).json()
    mine = next(c for c in listed if c["id"] == body["id"])
    assert mine["chore_kind"] == "standing"
    assert mine["standing_on"] is True
    assert mine["outcome_tiers"][0]["text"] == "grounded until it's fixed"


async def test_deactivating_a_standing_chore_turns_it_off(client, admin_user, child_user):
    """A retired chore must not leave a live consequence on the kid's home screen."""
    h = await _admin_headers(client)
    body = await _mk(client, h, child_user)
    await client.post(
        f"/api/v1/chores/{body['id']}/state", json={"on": True, "tier_id": 1}, headers=h
    )

    assert (await client.delete(f"/api/v1/chores/{body['id']}", headers=h)).status_code == 204

    after = (await client.get(f"/api/v1/chores/{body['id']}", headers=h)).json()
    assert after["active"] is False
    assert after["standing_on"] is False


async def test_chore_kind_cannot_be_patched(client, admin_user, child_user):
    """Flipping a saved chore between kinds would strand its occurrences — duplicate instead."""
    h = await _admin_headers(client)
    body = await _mk(client, h, child_user)

    r = await client.patch(
        f"/api/v1/chores/{body['id']}", json={"chore_kind": "scheduled"}, headers=h
    )
    assert r.status_code == 422


async def test_a_standing_chore_can_be_duplicated(client, admin_user, child_user):
    """The documented path for "I want this as a scheduled chore instead"."""
    h = await _admin_headers(client)
    body = await _mk(client, h, child_user)
    await client.post(
        f"/api/v1/chores/{body['id']}/state", json={"on": True, "tier_id": 1}, headers=h
    )

    r = await client.post(f"/api/v1/chores/{body['id']}/duplicate", headers=h)
    assert r.status_code == 201
    copy = r.json()
    assert copy["chore_kind"] == "standing"
    assert copy["outcome_tiers"] == body["outcome_tiers"]
    # a fresh copy starts off, not carrying the original's live state
    assert copy["standing_on"] is False


# --------------------------------------------------------------- unchanged saves

# Exactly the frontend's PATCH allowlist (frontend/src/admin/chores/choreFields.ts EDITABLE)
# plus late_multiplier, which body() injects for a tiered chore. Kept here so a drift between
# the two lists shows up as a failing test rather than a 422 in a parent's face.
_EDITABLE = [
    "title",
    "description",
    "assignment_mode",
    "fixed_assignee_id",
    "assignee_ids",
    "rotation_period",
    "rotation_anchor_date",
    "cadence",
    "due_time",
    "window_open_offset_s",
    "grace_period_s",
    "end_date",
    "geofence",
    "photo_count",
    "photo_prompts",
    "allow_gallery_upload",
    "verification_mode",
    "verification_checklist",
    "outcome_tiers",
    "reward_cents",
    "penalty_cents",
    "auto_pass_threshold",
    "auto_fail_threshold",
    "late_multiplier",
]


def _resave(body: dict) -> dict:
    return {k: body[k] for k in _EDITABLE}


async def test_a_standing_chore_survives_an_unchanged_full_patch(client, admin_user, child_user):
    h = await _admin_headers(client)
    body = await _mk(client, h, child_user)

    r = await client.patch(f"/api/v1/chores/{body['id']}", json=_resave(body), headers=h)
    assert r.status_code == 200, r.json()
    for k in _EDITABLE:
        assert r.json()[k] == body[k], k


async def test_a_standing_chore_survives_a_full_patch_after_being_flipped(
    client, admin_user, child_user
):
    """The exact sequence behind the "[object Object]" report: open it, flip it on, flip it
    off, then save the form untouched."""
    h = await _admin_headers(client)
    body = await _mk(client, h, child_user)

    await client.post(
        f"/api/v1/chores/{body['id']}/state", json={"on": True, "tier_id": 1}, headers=h
    )
    await client.post(f"/api/v1/chores/{body['id']}/state", json={"on": False}, headers=h)

    r = await client.patch(f"/api/v1/chores/{body['id']}", json=_resave(body), headers=h)
    assert r.status_code == 200, r.json()


async def test_a_patch_cannot_smuggle_the_standing_state(client, admin_user, child_user):
    """standing_on/tier/since are set only by the flip endpoint; ChoreUpdate forbids extras."""
    h = await _admin_headers(client)
    body = await _mk(client, h, child_user)
    await client.post(
        f"/api/v1/chores/{body['id']}/state", json={"on": True, "tier_id": 1}, headers=h
    )

    r = await client.patch(
        f"/api/v1/chores/{body['id']}", json=_resave(body) | {"standing_on": False}, headers=h
    )
    assert r.status_code == 422

    still = (await client.get(f"/api/v1/chores/{body['id']}", headers=h)).json()
    assert still["standing_on"] is True


async def test_a_blank_tier_condition_is_rejected_as_a_field_error(client, admin_user, child_user):
    """Pins the response shape the frontend's detailText() renders — a list of field errors
    whose loc names the offending row."""
    h = await _admin_headers(client)
    body = await _mk(client, h, child_user)

    r = await client.patch(
        f"/api/v1/chores/{body['id']}",
        json=_resave(body)
        | {"outcome_tiers": [{"id": 1, "condition": "", "outcome_kind": "text", "text": "x"}]},
        headers=h,
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert isinstance(detail, list)
    assert detail[0]["loc"][-1] == "condition"


# --------------------------------------------------------------- notifications

# VAPID is unset in tests, so nothing is actually delivered — assert against the log rows,
# the same way test_push.py does.


async def _logs(db, kind: str | None = None) -> list[NotificationLog]:
    rows = (await db.execute(select(NotificationLog))).scalars().all()
    return [r for r in rows if kind is None or r.kind == kind]


async def test_turning_it_on_tells_the_kid_what_is_in_force(
    client, db_session, admin_user, child_user
):
    h = await _admin_headers(client)
    body = await _mk(client, h, child_user)

    await client.post(
        f"/api/v1/chores/{body['id']}/state",
        json={"on": True, "tier_id": 1, "note": "third one this week"},
        headers=h,
    )

    (row,) = await _logs(db_session, "standing.on")
    assert row.user_id == child_user.id
    assert row.title == "grounded until it's fixed"
    assert "more than one missing assignment" in row.body
    assert "third one this week" in row.body
    assert row.url == "/me"
    assert row.status in ("skipped", "no_subs")


async def test_turning_it_off_tells_the_kid_it_is_lifted(
    client, db_session, admin_user, child_user
):
    h = await _admin_headers(client)
    body = await _mk(client, h, child_user)
    await client.post(
        f"/api/v1/chores/{body['id']}/state", json={"on": True, "tier_id": 1}, headers=h
    )
    await client.post(f"/api/v1/chores/{body['id']}/state", json={"on": False}, headers=h)

    (row,) = await _logs(db_session, "standing.off")
    assert row.user_id == child_user.id
    assert "lifted" in row.title.lower()
    assert row.body == "Missing assignments"


async def test_a_repeated_flip_sends_nothing(client, db_session, admin_user, child_user):
    h = await _admin_headers(client)
    body = await _mk(client, h, child_user)
    for _ in range(2):
        await client.post(
            f"/api/v1/chores/{body['id']}/state", json={"on": True, "tier_id": 1}, headers=h
        )

    assert len(await _logs(db_session, "standing.on")) == 1


async def test_turning_off_something_that_was_never_on_sends_nothing(
    client, db_session, admin_user, child_user
):
    """The idempotent short-circuit only fires once a flip history exists, so this path
    reaches the notify call with nothing to announce."""
    h = await _admin_headers(client)
    body = await _mk(client, h, child_user)

    await client.post(f"/api/v1/chores/{body['id']}/state", json={"on": False}, headers=h)

    assert await _logs(db_session, "standing.off") == []


async def test_deactivating_a_live_standing_chore_tells_the_kid(
    client, db_session, admin_user, child_user
):
    h = await _admin_headers(client)
    body = await _mk(client, h, child_user)
    await client.post(
        f"/api/v1/chores/{body['id']}/state", json={"on": True, "tier_id": 1}, headers=h
    )

    await client.delete(f"/api/v1/chores/{body['id']}", headers=h)

    assert len(await _logs(db_session, "standing.off")) == 1


async def test_every_assignee_of_an_all_mode_chore_is_told(
    client, db_session, household, admin_user, child_user
):
    second = User(
        household_id=household.id,
        username="kid2",
        display_name="Kid Two",
        role=UserRole.child,
    )
    db_session.add(second)
    await db_session.commit()

    h = await _admin_headers(client)
    body = await _mk(
        client,
        h,
        child_user,
        assignment_mode="all",
        fixed_assignee_id=None,
        assignee_ids=[str(child_user.id), str(second.id)],
    )
    await client.post(
        f"/api/v1/chores/{body['id']}/state", json={"on": True, "tier_id": 1}, headers=h
    )

    rows = await _logs(db_session, "standing.on")
    assert {r.user_id for r in rows} == {child_user.id, second.id}


async def test_a_flip_never_notifies_a_parent(client, db_session, admin_user, child_user):
    """Whose rule is in force is the assignee's own business (spec §15 Q1), and the parent
    who flipped it already knows."""
    h = await _admin_headers(client)
    body = await _mk(client, h, child_user)
    await client.post(
        f"/api/v1/chores/{body['id']}/state", json={"on": True, "tier_id": 1}, headers=h
    )

    assert all(r.user_id != admin_user.id for r in await _logs(db_session))
