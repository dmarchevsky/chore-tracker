"""Penalty rules: a published price list a parent charges against (spec §4.8)."""

from __future__ import annotations

import uuid as uuidlib

import pytest
from sqlalchemy import func, select
from tests.helpers import sign_in

from app.models import AuditLog, ChoreOccurrence, LedgerEntry, NotificationLog, User, UserRole
from app.services.ledger import balance_cents
from app.services.scheduler import reconcile

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _parent(admin_user):
    """Every test here signs in as the parent, so the row has to exist first."""


BIKE = [
    {
        "id": 1,
        "condition": "bike left in the driveway",
        "outcome_kind": "money",
        "amount_cents": -200,
    },
    {
        "id": 2,
        "condition": "left out again the same week",
        "outcome_kind": "money",
        "amount_cents": -500,
    },
]


async def _admin_headers(client) -> dict:
    r = await sign_in(client, "parent@example.com")
    return {"X-CSRF-Token": r.json()["csrf_token"]}


async def _kid_headers(client) -> dict:
    r = await sign_in(client, "alice@example.com")
    return {"X-CSRF-Token": r.json()["csrf_token"]}


def _rule_body(child, **over) -> dict:
    body = {
        "chore_kind": "penalty",
        "title": "Bike left out",
        "assignment_mode": "fixed",
        "fixed_assignee_id": str(child.id),
        "outcome_tiers": BIKE,
    }
    body.update(over)
    return body


async def _create_rule(client, headers, child, **over) -> dict:
    r = await client.post("/api/v1/chores", json=_rule_body(child, **over), headers=headers)
    assert r.status_code == 201, r.json()
    return r.json()


# --- Defining the rule -------------------------------------------------


async def test_create_penalty_rule_fills_the_schedule_columns(client, child_user):
    """A parent never sees cadence/proof/verification for a penalty rule, so the schema
    fills them — and the round-trip proves the stored definition is coherent."""
    h = await _admin_headers(client)
    rule = await _create_rule(client, h, child_user)

    assert rule["chore_kind"] == "penalty"
    assert rule["cadence"] == "penalty"
    assert rule["proof_type"] == "none"
    assert rule["verification_mode"] == "manual"
    assert rule["reward_cents"] == 0 and rule["penalty_cents"] == 0
    assert [t["amount_cents"] for t in rule["outcome_tiers"]] == [-200, -500]


@pytest.mark.parametrize(
    "over",
    [
        pytest.param(
            {
                "outcome_tiers": [
                    {"id": 1, "condition": "x", "outcome_kind": "money", "amount_cents": 200}
                ]
            },
            id="a positive tier is a reward, not a penalty",
        ),
        pytest.param(
            {
                "outcome_tiers": [
                    {"id": 1, "condition": "x", "outcome_kind": "text", "text": "grounded"}
                ]
            },
            id="a text tier moves no money",
        ),
        pytest.param({"outcome_tiers": []}, id="no conditions means nothing to charge for"),
        pytest.param(
            {
                "outcome_tiers": [
                    {"id": 2, "condition": "x", "outcome_kind": "money", "amount_cents": -200}
                ]
            },
            id="tier ids must be 1..N",
        ),
        pytest.param(
            {"assignment_mode": "anyone", "fixed_assignee_id": None},
            id="anyone has nobody to charge",
        ),
        pytest.param({"reward_cents": 100}, id="money comes from the tiers"),
        pytest.param({"late_multiplier": 0.5}, id="no schedule means nothing is late"),
        pytest.param({"end_date": "2030-01-01"}, id="deactivate it instead of ending it"),
        pytest.param({"proof_type": "photo", "photo_count": 1}, id="a penalty takes no proof"),
    ],
)
async def test_penalty_rule_rejects_an_incoherent_definition(client, child_user, over):
    h = await _admin_headers(client)
    r = await client.post("/api/v1/chores", json=_rule_body(child_user, **over), headers=h)
    assert r.status_code == 422, r.json()


async def test_a_penalty_rule_generates_no_occurrences(client, db_session, child_user):
    """It is a price list, not a schedule — the scheduler must not materialise it."""
    h = await _admin_headers(client)
    await _create_rule(client, h, child_user)

    await reconcile(db_session)
    count = await db_session.scalar(select(func.count()).select_from(ChoreOccurrence))
    assert count == 0


# --- Applying it -------------------------------------------------------


async def test_apply_charges_the_kid_and_names_the_rule(client, db_session, child_user):
    h = await _admin_headers(client)
    rule = await _create_rule(client, h, child_user)

    r = await client.post(
        "/api/v1/penalties",
        json={
            "chore_id": rule["id"],
            "child_id": str(child_user.id),
            "tier_id": 1,
            "note": "third time this week",
        },
        headers=h,
    )
    assert r.status_code == 201, r.json()
    entry = r.json()

    assert entry["kind"] == "penalty"
    assert entry["amount_cents"] == -200
    assert entry["occurrence_id"] is None
    assert entry["chore_id"] == rule["id"]
    # The kid reads this line on their statement: rule, condition, then the parent's words.
    assert entry["reason"] == "Bike left out: bike left in the driveway — third time this week"
    assert await balance_cents(db_session, child_user.id) == -200


async def test_apply_notifies_only_the_kid_and_is_audited(client, db_session, child_user):
    h = await _admin_headers(client)
    rule = await _create_rule(client, h, child_user)
    await client.post(
        "/api/v1/penalties",
        json={"chore_id": rule["id"], "child_id": str(child_user.id), "tier_id": 2},
        headers=h,
    )

    notes = list((await db_session.execute(select(NotificationLog))).scalars())
    assert [n.user_id for n in notes] == [child_user.id]
    assert notes[0].kind == "penalty.applied"

    actions = list(
        (await db_session.execute(select(AuditLog.action).order_by(AuditLog.created_at))).scalars()
    )
    assert "penalty.apply" in actions


async def test_amount_override_wins_and_is_always_a_debit(client, db_session, child_user):
    """The client sends a positive magnitude and the service applies the sign, like a
    payout — a parent never types a minus."""
    h = await _admin_headers(client)
    rule = await _create_rule(client, h, child_user)

    r = await client.post(
        "/api/v1/penalties",
        json={
            "chore_id": rule["id"],
            "child_id": str(child_user.id),
            "tier_id": 1,
            "amount_override_cents": 350,
        },
        headers=h,
    )
    assert r.status_code == 201, r.json()
    assert r.json()["amount_cents"] == -350


async def test_applying_twice_charges_twice(client, db_session, child_user):
    """Not idempotent, deliberately: a rule can genuinely be broken twice in a day, and
    there is no occurrence for "the same charge" to mean anything against."""
    h = await _admin_headers(client)
    rule = await _create_rule(client, h, child_user)
    body = {"chore_id": rule["id"], "child_id": str(child_user.id), "tier_id": 1}

    first = await client.post("/api/v1/penalties", json=body, headers=h)
    second = await client.post("/api/v1/penalties", json=body, headers=h)
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert await balance_cents(db_session, child_user.id) == -400


async def test_apply_rejects_a_kid_the_rule_does_not_target(
    client, db_session, child_user, household
):
    h = await _admin_headers(client)
    rule = await _create_rule(client, h, child_user)
    sibling = User(
        household_id=household.id,
        username="bob",
        display_name="Bob",
        role=UserRole.child,
        email="bob@example.com",
    )
    db_session.add(sibling)
    await db_session.commit()

    r = await client.post(
        "/api/v1/penalties",
        json={"chore_id": rule["id"], "child_id": str(sibling.id), "tier_id": 1},
        headers=h,
    )
    assert r.status_code == 409, r.json()
    assert await balance_cents(db_session, sibling.id) == 0


async def test_apply_rejects_a_deactivated_rule(client, child_user):
    h = await _admin_headers(client)
    rule = await _create_rule(client, h, child_user)
    assert (await client.delete(f"/api/v1/chores/{rule['id']}", headers=h)).status_code in (
        200,
        204,
    )

    r = await client.post(
        "/api/v1/penalties",
        json={"chore_id": rule["id"], "child_id": str(child_user.id), "tier_id": 1},
        headers=h,
    )
    assert r.status_code == 409, r.json()


async def test_apply_rejects_a_scheduled_chore_and_an_unknown_tier(client, child_user):
    h = await _admin_headers(client)
    rule = await _create_rule(client, h, child_user)
    scheduled = await client.post(
        "/api/v1/chores",
        json={
            "title": "Dishes",
            "assignment_mode": "fixed",
            "fixed_assignee_id": str(child_user.id),
            "cadence": "daily",
            "due_time": "18:00:00",
            "start_date": "2026-01-01",
            "proof_type": "acknowledgement",
            "verification_mode": "manual",
            "reward_cents": 100,
        },
        headers=h,
    )
    assert scheduled.status_code == 201, scheduled.json()

    r = await client.post(
        "/api/v1/penalties",
        json={"chore_id": scheduled.json()["id"], "child_id": str(child_user.id), "tier_id": 1},
        headers=h,
    )
    assert r.status_code == 409, r.json()

    r = await client.post(
        "/api/v1/penalties",
        json={"chore_id": rule["id"], "child_id": str(child_user.id), "tier_id": 7},
        headers=h,
    )
    assert r.status_code == 409, r.json()


async def test_a_kid_cannot_apply_or_undo_a_penalty(client, child_user):
    admin_h = await _admin_headers(client)
    rule = await _create_rule(client, admin_h, child_user)
    applied = await client.post(
        "/api/v1/penalties",
        json={"chore_id": rule["id"], "child_id": str(child_user.id), "tier_id": 1},
        headers=admin_h,
    )

    kid_h = await _kid_headers(client)
    r = await client.post(
        "/api/v1/penalties",
        json={"chore_id": rule["id"], "child_id": str(child_user.id), "tier_id": 1},
        headers=kid_h,
    )
    assert r.status_code == 403, r.json()

    r = await client.post(
        f"/api/v1/penalties/{applied.json()['id']}/reverse",
        json={"reason": "no I didn't"},
        headers=kid_h,
    )
    assert r.status_code == 403, r.json()


async def test_apply_404s_on_an_unknown_rule_or_child(client, child_user):
    h = await _admin_headers(client)
    rule = await _create_rule(client, h, child_user)
    ghost = str(uuidlib.uuid4())

    r = await client.post(
        "/api/v1/penalties",
        json={"chore_id": ghost, "child_id": str(child_user.id), "tier_id": 1},
        headers=h,
    )
    assert r.status_code == 404
    r = await client.post(
        "/api/v1/penalties",
        json={"chore_id": rule["id"], "child_id": ghost, "tier_id": 1},
        headers=h,
    )
    assert r.status_code == 404


# --- Undoing it --------------------------------------------------------


async def test_reverse_restores_the_balance_append_only(client, db_session, child_user):
    h = await _admin_headers(client)
    rule = await _create_rule(client, h, child_user)
    applied = (
        await client.post(
            "/api/v1/penalties",
            json={"chore_id": rule["id"], "child_id": str(child_user.id), "tier_id": 1},
            headers=h,
        )
    ).json()

    r = await client.post(
        f"/api/v1/penalties/{applied['id']}/reverse",
        json={"reason": "it was the neighbour's bike"},
        headers=h,
    )
    assert r.status_code == 201, r.json()
    assert r.json()["kind"] == "adjustment"
    assert r.json()["amount_cents"] == 200

    assert await balance_cents(db_session, child_user.id) == 0
    original = await db_session.get(LedgerEntry, uuidlib.UUID(applied["id"]))
    await db_session.refresh(original)
    assert original.reversed_by_entry_id is not None
    # Append-only: the charge is still on the statement, with its undo beside it (spec §9).
    count = await db_session.scalar(select(func.count()).select_from(LedgerEntry))
    assert count == 2


async def test_a_penalty_cannot_be_undone_twice(client, child_user):
    h = await _admin_headers(client)
    rule = await _create_rule(client, h, child_user)
    applied = (
        await client.post(
            "/api/v1/penalties",
            json={"chore_id": rule["id"], "child_id": str(child_user.id), "tier_id": 1},
            headers=h,
        )
    ).json()
    body = {"reason": "mistake"}

    assert (
        await client.post(f"/api/v1/penalties/{applied['id']}/reverse", json=body, headers=h)
    ).status_code == 201
    r = await client.post(f"/api/v1/penalties/{applied['id']}/reverse", json=body, headers=h)
    assert r.status_code == 409, r.json()


async def test_reverse_refuses_an_occurrence_backed_entry(
    client, db_session, child_user, household
):
    """A missed chore is undone by excusing the occurrence, which also clears its state.
    Reversing it here would move the money back and leave the miss still reading as charged."""
    h = await _admin_headers(client)
    entry = LedgerEntry(
        household_id=household.id,
        child_id=child_user.id,
        occurrence_id=None,
        kind="penalty",
        amount_cents=-100,
        reason="chore missed",
    )
    db_session.add(entry)
    await db_session.commit()

    r = await client.post(
        f"/api/v1/penalties/{entry.id}/reverse", json={"reason": "nope"}, headers=h
    )
    # No chore_id and no occurrence: not something this endpoint owns.
    assert r.status_code == 409, r.json()


# --- Where it shows up -------------------------------------------------


async def test_the_statement_names_the_rule_for_a_manual_penalty(client, child_user):
    """A manual penalty has no occurrence to reach its chore through, so the statement
    join has to find it by chore_id — otherwise the line reads with no rule at all."""
    h = await _admin_headers(client)
    rule = await _create_rule(client, h, child_user)
    await client.post(
        "/api/v1/penalties",
        json={"chore_id": rule["id"], "child_id": str(child_user.id), "tier_id": 1},
        headers=h,
    )

    rows = (await client.get(f"/api/v1/children/{child_user.id}/ledger", headers=h)).json()
    assert len(rows) == 1
    assert rows[0]["chore_title"] == "Bike left out"
    assert rows[0]["occurrence_due_at"] is None
    assert rows[0]["chore_id"] == rule["id"]


async def test_the_kid_sees_their_own_penalty_rule(client, child_user):
    """Transparency reduces arguments (spec §15 Q8): the price list is published."""
    admin_h = await _admin_headers(client)
    rule = await _create_rule(client, admin_h, child_user)

    kid_h = await _kid_headers(client)
    chores = (await client.get("/api/v1/chores", headers=kid_h)).json()
    assert [c["id"] for c in chores] == [rule["id"]]
    assert chores[0]["outcome_tiers"][0]["condition"] == "bike left in the driveway"


async def test_the_penalty_cadence_never_fires(client, child_user):
    """Defence in depth, matching the standing token: even a code path that forgot to filter
    on chore_kind would generate nothing from a penalty rule (spec §4.7, §4.8)."""
    from datetime import date

    from app.services.cadence import cadence_dates

    assert cadence_dates("penalty", date(2026, 1, 1), date(2027, 1, 1)) == []
