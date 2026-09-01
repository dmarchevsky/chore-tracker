"""Phase 2: chore CRUD, preview, occurrence listing + assignee swap (spec §4.1, §8.2, §10)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.models import AuditLog, ChoreOccurrence, OccurrenceStatus, User, UserRole
from app.schemas.chore import ChoreBase
from app.services.scheduler import generate_occurrences

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def second_child(db_session, household) -> User:
    u = User(
        household_id=household.id,
        username="bea",
        display_name="Bea",
        role=UserRole.child,
        password_hash="x",
    )
    db_session.add(u)
    await db_session.commit()
    return u


async def _admin_headers(client, admin_user, totp_now) -> dict:
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "parent", "password": "parent-pass", "totp_code": totp_now()},
    )
    assert r.status_code == 200
    return {"X-CSRF-Token": r.json()["csrf_token"]}


def _fixed_body(a: User, **over) -> dict:
    body = {
        "title": "Dishes",
        "assignment_mode": "fixed",
        "fixed_assignee_id": str(a.id),
        "cadence": "daily",
        "due_time": "08:00:00",
        "start_date": "2025-01-01",
        "proof_type": "photo",
        "photo_count": 1,
        "verification_mode": "manual",
        "reward_cents": 100,
    }
    body.update(over)
    return body


def _rotating_body(a: User, b: User, **over) -> dict:
    body = {
        "title": "Kitchen",
        "assignment_mode": "rotating",
        "assignee_ids": [str(a.id), str(b.id)],
        "rotation_period": "biweekly",
        "rotation_anchor_date": "2025-06-02",
        "cadence": "weekly(on=[MON])",
        "due_time": "08:00:00",
        "start_date": "2025-01-01",
        "proof_type": "photo",
        "photo_count": 1,
        "verification_mode": "llm_auto",
        "reward_cents": 200,
    }
    body.update(over)
    return body


async def test_create_list_get_chore(client, admin_user, child_user, second_child, totp_now):
    h = await _admin_headers(client, admin_user, totp_now)

    r = await client.post(
        "/api/v1/chores", json=_rotating_body(child_user, second_child), headers=h
    )
    assert r.status_code == 201, r.text
    chore_id = r.json()["id"]
    assert r.json()["assignment_mode"] == "rotating"

    lst = await client.get("/api/v1/chores", headers=h)
    assert [c["id"] for c in lst.json()] == [chore_id]

    got = await client.get(f"/api/v1/chores/{chore_id}", headers=h)
    assert got.status_code == 200
    assert got.json()["reward_cents"] == 200


async def test_create_rejects_unknown_assignee(client, admin_user, child_user, totp_now):
    h = await _admin_headers(client, admin_user, totp_now)
    body = _rotating_body(child_user, child_user)
    body["assignee_ids"] = [str(child_user.id), "00000000-0000-0000-0000-000000000009"]
    r = await client.post("/api/v1/chores", json=body, headers=h)
    assert r.status_code == 422


async def test_preview_is_biweekly_alice_alice_bea_bea(
    client, admin_user, child_user, second_child, totp_now
):
    h = await _admin_headers(client, admin_user, totp_now)
    r = await client.post(
        "/api/v1/chores/preview?count=4&from_date=2025-06-01",
        json=_rotating_body(child_user, second_child),
        headers=h,
    )
    assert r.status_code == 200
    items = r.json()
    assert [i["due_at"][:10] for i in items] == [
        "2025-06-02",
        "2025-06-09",
        "2025-06-16",
        "2025-06-23",
    ]
    assert [i["assignee_id"] for i in items] == [
        str(child_user.id),
        str(child_user.id),
        str(second_child.id),
        str(second_child.id),
    ]


async def test_patch_updates_definition(client, admin_user, child_user, second_child, totp_now):
    h = await _admin_headers(client, admin_user, totp_now)
    chore_id = (
        await client.post(
            "/api/v1/chores", json=_rotating_body(child_user, second_child), headers=h
        )
    ).json()["id"]

    r = await client.patch(f"/api/v1/chores/{chore_id}", json={"reward_cents": 500}, headers=h)
    assert r.status_code == 200 and r.json()["reward_cents"] == 500


async def test_patch_regenerates_upcoming_occurrences(
    client, admin_user, child_user, second_child, totp_now, db_session
):
    h = await _admin_headers(client, admin_user, totp_now)
    chore_id = (
        await client.post(
            "/api/v1/chores",
            json=_rotating_body(child_user, second_child, cadence="daily"),
            headers=h,
        )
    ).json()["id"]

    now = datetime.now(UTC)
    future_rewards = (
        select(ChoreOccurrence.reward_cents)
        .where(ChoreOccurrence.chore_id == uuid.UUID(chore_id), ChoreOccurrence.due_at > now)
        .distinct()
    )
    # create already materialised the horizon at the original reward
    assert set((await db_session.execute(future_rewards)).scalars()) == {200}

    r = await client.patch(f"/api/v1/chores/{chore_id}", json={"reward_cents": 999}, headers=h)
    assert r.status_code == 200

    # no ?apply flag — the edit is reflected in the upcoming occurrences immediately
    assert set((await db_session.execute(future_rewards)).scalars()) == {999}


async def test_patch_reassign_regenerates_with_new_assignee(
    client, admin_user, child_user, second_child, totp_now, db_session
):
    h = await _admin_headers(client, admin_user, totp_now)
    chore_id = (
        await client.post(
            "/api/v1/chores", json=_fixed_body(child_user, cadence="daily"), headers=h
        )
    ).json()["id"]

    now = datetime.now(UTC)
    future_assignees = (
        select(ChoreOccurrence.assignee_id)
        .where(ChoreOccurrence.chore_id == uuid.UUID(chore_id), ChoreOccurrence.due_at > now)
        .distinct()
    )
    assert set((await db_session.execute(future_assignees)).scalars()) == {child_user.id}

    r = await client.patch(
        f"/api/v1/chores/{chore_id}",
        json={"fixed_assignee_id": str(second_child.id)},
        headers=h,
    )
    assert r.status_code == 200
    assert set((await db_session.execute(future_assignees)).scalars()) == {second_child.id}


async def test_patch_reassigns_fixed_chore(client, admin_user, child_user, second_child, totp_now):
    h = await _admin_headers(client, admin_user, totp_now)
    chore_id = (
        await client.post("/api/v1/chores", json=_fixed_body(child_user), headers=h)
    ).json()["id"]

    r = await client.patch(
        f"/api/v1/chores/{chore_id}",
        json={"fixed_assignee_id": str(second_child.id)},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["fixed_assignee_id"] == str(second_child.id)


async def test_patch_reassign_rejects_unknown_assignee(client, admin_user, child_user, totp_now):
    h = await _admin_headers(client, admin_user, totp_now)
    chore_id = (
        await client.post("/api/v1/chores", json=_fixed_body(child_user), headers=h)
    ).json()["id"]

    r = await client.patch(
        f"/api/v1/chores/{chore_id}",
        json={"fixed_assignee_id": "00000000-0000-0000-0000-000000000009"},
        headers=h,
    )
    assert r.status_code == 422


async def test_patch_to_rotating_needs_two_assignees(
    client, admin_user, child_user, second_child, totp_now
):
    h = await _admin_headers(client, admin_user, totp_now)
    chore_id = (
        await client.post(
            "/api/v1/chores", json=_rotating_body(child_user, second_child), headers=h
        )
    ).json()["id"]

    r = await client.patch(
        f"/api/v1/chores/{chore_id}",
        json={"assignee_ids": [str(child_user.id)]},
        headers=h,
    )
    assert r.status_code == 422


async def test_patch_rejects_threshold_inversion(client, admin_user, child_user, totp_now):
    h = await _admin_headers(client, admin_user, totp_now)
    chore_id = (
        await client.post("/api/v1/chores", json=_fixed_body(child_user), headers=h)
    ).json()["id"]

    # default auto_pass_threshold is 0.85; a higher auto_fail is invalid (spec §6.3).
    r = await client.patch(
        f"/api/v1/chores/{chore_id}", json={"auto_fail_threshold": 0.95}, headers=h
    )
    assert r.status_code == 422


async def test_patch_threshold_audits_decimal_snapshot(
    client, admin_user, child_user, totp_now, db_session
):
    # The `before` audit snapshot pulls Numeric columns off the ORM as Decimal;
    # _json() must coerce them or the audit_log INSERT blows up with a 500.
    h = await _admin_headers(client, admin_user, totp_now)
    chore_id = (
        await client.post("/api/v1/chores", json=_fixed_body(child_user), headers=h)
    ).json()["id"]

    r = await client.patch(
        f"/api/v1/chores/{chore_id}",
        json={"auto_pass_threshold": 0.9, "late_multiplier": 0.5},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["auto_pass_threshold"] == 0.9

    row = (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "chore.update"))
    ).scalar_one()
    assert row.before["auto_pass_threshold"] == 0.85  # serialized, not a Decimal
    assert row.after["late_multiplier"] == 0.5


async def test_deactivate_drops_future_occurrences(
    client, admin_user, child_user, totp_now, db_session
):
    h = await _admin_headers(client, admin_user, totp_now)
    chore_id = (
        await client.post("/api/v1/chores", json=_fixed_body(child_user), headers=h)
    ).json()["id"]

    await generate_occurrences(db_session)
    await db_session.commit()

    future_for_chore = (
        select(func.count())
        .select_from(ChoreOccurrence)
        .where(
            ChoreOccurrence.chore_id == uuid.UUID(chore_id),
            ChoreOccurrence.due_at > datetime.now(UTC),
            ChoreOccurrence.status.in_([OccurrenceStatus.pending, OccurrenceStatus.open]),
        )
    )
    assert (await db_session.execute(future_for_chore)).scalar_one() > 0

    assert (await client.delete(f"/api/v1/chores/{chore_id}", headers=h)).status_code == 204
    assert (await db_session.execute(future_for_chore)).scalar_one() == 0


async def test_delete_is_soft(client, admin_user, child_user, second_child, totp_now):
    h = await _admin_headers(client, admin_user, totp_now)
    chore_id = (
        await client.post(
            "/api/v1/chores", json=_rotating_body(child_user, second_child), headers=h
        )
    ).json()["id"]

    assert (await client.delete(f"/api/v1/chores/{chore_id}", headers=h)).status_code == 204
    assert (await client.get("/api/v1/chores", headers=h)).json() == []
    assert (await client.get("/api/v1/chores?include_inactive=true", headers=h)).json()[0][
        "active"
    ] is False


async def test_child_reads_active_chores_only(
    client, admin_user, child_user, second_child, totp_now
):
    h = await _admin_headers(client, admin_user, totp_now)
    keep = (await client.post("/api/v1/chores", json=_fixed_body(child_user), headers=h)).json()[
        "id"
    ]
    gone = (
        await client.post(
            "/api/v1/chores", json=_fixed_body(child_user, title="Retired"), headers=h
        )
    ).json()["id"]
    await client.delete(f"/api/v1/chores/{gone}", headers=h)

    login = await client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "alice-pass"}
    )
    kh = {"X-CSRF-Token": login.json()["csrf_token"]}

    lst = await client.get("/api/v1/chores")
    assert lst.status_code == 200
    assert [c["id"] for c in lst.json()] == [keep]
    # include_inactive is admin-only — a kid can't see the retired chore
    assert [c["id"] for c in (await client.get("/api/v1/chores?include_inactive=true")).json()] == [
        keep
    ]

    assert (await client.get(f"/api/v1/chores/{keep}")).status_code == 200
    assert (await client.get(f"/api/v1/chores/{gone}")).status_code == 404

    # writes stay admin-only
    assert (
        await client.post("/api/v1/chores", json=_fixed_body(child_user), headers=kh)
    ).status_code == 403
    assert (
        await client.patch(f"/api/v1/chores/{keep}", json={"reward_cents": 999}, headers=kh)
    ).status_code == 403


async def test_occurrences_scoped_and_assignee_swap(
    client, admin_user, child_user, second_child, totp_now, db_session
):
    h = await _admin_headers(client, admin_user, totp_now)
    await client.post(
        "/api/v1/chores",
        json=_rotating_body(child_user, second_child, cadence="daily"),
        headers=h,
    )
    await generate_occurrences(db_session)
    await db_session.commit()

    # Admin sees everything. Use the furthest-out occurrence — always still pending.
    all_occ = (await client.get("/api/v1/occurrences", headers=h)).json()
    assert len(all_occ) > 0
    target = all_occ[-1]["id"]

    # Child sees only their own.
    await client.post("/api/v1/auth/login", json={"username": "alice", "password": "alice-pass"})
    mine = (await client.get("/api/v1/occurrences")).json()
    assert all(o["assignee_id"] == str(child_user.id) for o in mine)

    # Swap needs admin + CSRF; re-login mints a fresh CSRF token.
    relog = await client.post(
        "/api/v1/auth/login",
        json={"username": "parent", "password": "parent-pass", "totp_code": totp_now()},
    )
    r = await client.patch(
        f"/api/v1/occurrences/{target}/assignee",
        json={"assignee_id": str(second_child.id)},
        headers={"X-CSRF-Token": relog.json()["csrf_token"]},
    )
    assert r.status_code == 200 and r.json()["assignee_id"] == str(second_child.id)

    n_audit = (
        await db_session.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "occurrence.swap_assignee")
        )
    ).scalar_one()
    assert n_audit == 1


async def test_occurrences_order_desc(
    client, admin_user, child_user, second_child, totp_now, db_session
):
    h = await _admin_headers(client, admin_user, totp_now)
    await client.post(
        "/api/v1/chores",
        json=_rotating_body(child_user, second_child, cadence="daily"),
        headers=h,
    )
    await generate_occurrences(db_session)
    await db_session.commit()

    asc = [o["due_at"] for o in (await client.get("/api/v1/occurrences", headers=h)).json()]
    desc = [
        o["due_at"] for o in (await client.get("/api/v1/occurrences?order=desc", headers=h)).json()
    ]
    assert asc == sorted(asc)
    assert desc == sorted(desc, reverse=True)
    assert desc[0] == asc[-1]


async def test_assignee_swap_forbidden_for_child(
    client, admin_user, child_user, second_child, totp_now, db_session
):
    h = await _admin_headers(client, admin_user, totp_now)
    await client.post(
        "/api/v1/chores",
        json=_rotating_body(child_user, second_child, cadence="daily"),
        headers=h,
    )
    await generate_occurrences(db_session)
    await db_session.commit()
    occ_id = (await client.get("/api/v1/occurrences", headers=h)).json()[0]["id"]

    login = await client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "alice-pass"}
    )
    r = await client.patch(
        f"/api/v1/occurrences/{occ_id}/assignee",
        json={"assignee_id": str(second_child.id)},
        headers={"X-CSRF-Token": login.json()["csrf_token"]},
    )
    assert r.status_code == 403


async def test_geofence_is_creatable_and_editable(
    client, db_session, admin_user, child_user, totp_now
):
    """geofence was missing from ChoreUpdate, so a fence could only ever be set at
    creation — and the admin form had no control for it at all (spec §6.2)."""
    h = await _admin_headers(client, admin_user, totp_now)
    fence = {"lat": 37.7749, "lon": -122.4194, "radius_m": 120, "arrive_before": None}

    created = await client.post(
        "/api/v1/chores",
        json=_fixed_body(
            child_user,
            proof_type="location",
            photo_count=0,
            geofence=fence,
            verification_mode="auto_accept",
        ),
        headers=h,
    )
    assert created.status_code == 201, created.text
    chore_id = created.json()["id"]
    assert created.json()["geofence"]["radius_m"] == 120

    # arrive_before is a `time` once Pydantic has parsed it, nested inside the geofence
    # dict — the audit snapshot has to survive that (it used to 500 on the INSERT).
    moved = await client.patch(
        f"/api/v1/chores/{chore_id}",
        json={
            "geofence": {
                "lat": 40.7128,
                "lon": -74.0060,
                "radius_m": 250,
                "arrive_before": "08:10",
            }
        },
        headers=h,
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["geofence"] == {
        "lat": 40.7128,
        "lon": -74.006,
        "radius_m": 250,
        "arrive_before": "08:10:00",
    }

    audited = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.action == "chore.update")
                .order_by(AuditLog.created_at)
            )
        )
        .scalars()
        .all()
    )
    assert audited[-1].after["geofence"]["arrive_before"] == "08:10:00"

    # A location chore without a fence is not a thing the state machine can evaluate.
    cleared = await client.patch(f"/api/v1/chores/{chore_id}", json={"geofence": None}, headers=h)
    assert cleared.status_code == 422
    assert "geofence" in cleared.text


async def test_duplicate_copies_every_definition_field(
    client, admin_user, child_user, totp_now, db_session
):
    """Spec §4.1: admin MUST be able to clone a chore. The copy has to carry the fields the
    admin form never renders (grace_period_s, end_date, late_multiplier) — dropping them is
    exactly the bug a client-side "prefill the create form" clone would have."""
    h = await _admin_headers(client, admin_user, totp_now)
    src = (
        await client.post(
            "/api/v1/chores",
            json=_fixed_body(
                child_user,
                grace_period_s=2700,
                end_date="2030-12-31",
                late_multiplier=0.5,
                window_open_offset_s=-7200,
                photo_prompts=["sink close-up"],
                description="under the sink too",
            ),
            headers=h,
        )
    ).json()

    r = await client.post(f"/api/v1/chores/{src['id']}/duplicate", headers=h)
    assert r.status_code == 201
    copy = r.json()

    assert copy["id"] != src["id"]
    carried = set(ChoreBase.model_fields) - {"title", "active"}
    assert {k: copy[k] for k in carried} == {k: src[k] for k in carried}


async def test_duplicate_starts_inactive_with_no_occurrences(
    client, admin_user, child_user, totp_now, db_session
):
    """A copy made in order to be edited must not push live work into a kid's list."""
    h = await _admin_headers(client, admin_user, totp_now)
    src = (await client.post("/api/v1/chores", json=_fixed_body(child_user), headers=h)).json()

    copy = (await client.post(f"/api/v1/chores/{src['id']}/duplicate", headers=h)).json()
    assert copy["active"] is False

    await generate_occurrences(db_session)
    n = await db_session.scalar(
        select(func.count())
        .select_from(ChoreOccurrence)
        .where(ChoreOccurrence.chore_id == uuid.UUID(copy["id"]))
    )
    assert n == 0


async def test_duplicate_titles_the_copy(client, admin_user, child_user, totp_now):
    h = await _admin_headers(client, admin_user, totp_now)
    src = (await client.post("/api/v1/chores", json=_fixed_body(child_user), headers=h)).json()

    default = (await client.post(f"/api/v1/chores/{src['id']}/duplicate", headers=h)).json()
    assert default["title"] == "Dishes (copy)"

    named = (
        await client.post(
            f"/api/v1/chores/{src['id']}/duplicate", json={"title": "Dishes v2"}, headers=h
        )
    ).json()
    assert named["title"] == "Dishes v2"


async def test_duplicate_keeps_a_long_title_within_the_column(
    client, admin_user, child_user, totp_now
):
    """title is String(160); the suffix must survive the cap, not be sliced off it."""
    h = await _admin_headers(client, admin_user, totp_now)
    src = (
        await client.post(
            "/api/v1/chores", json=_fixed_body(child_user, title="D" * 160), headers=h
        )
    ).json()

    copy = (await client.post(f"/api/v1/chores/{src['id']}/duplicate", headers=h)).json()
    assert len(copy["title"]) <= 160
    assert copy["title"].endswith(" (copy)")


async def test_duplicate_writes_an_audit_row(client, admin_user, child_user, totp_now, db_session):
    h = await _admin_headers(client, admin_user, totp_now)
    src = (await client.post("/api/v1/chores", json=_fixed_body(child_user), headers=h)).json()
    copy = (await client.post(f"/api/v1/chores/{src['id']}/duplicate", headers=h)).json()

    row = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "chore.duplicate", AuditLog.entity_id == copy["id"]
            )
        )
    ).scalar_one()
    assert row.after["source_chore_id"] == src["id"]
    assert row.actor_user_id == admin_user.id


async def test_duplicate_404_for_unknown_chore(client, admin_user, totp_now):
    h = await _admin_headers(client, admin_user, totp_now)
    r = await client.post(f"/api/v1/chores/{uuid.uuid4()}/duplicate", headers=h)
    assert r.status_code == 404


async def test_duplicate_is_admin_only(client, admin_user, child_user, totp_now):
    h = await _admin_headers(client, admin_user, totp_now)
    src = (await client.post("/api/v1/chores", json=_fixed_body(child_user), headers=h)).json()

    login = await client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "alice-pass"}
    )
    r = await client.post(
        f"/api/v1/chores/{src['id']}/duplicate",
        headers={"X-CSRF-Token": login.json()["csrf_token"]},
    )
    assert r.status_code == 403
