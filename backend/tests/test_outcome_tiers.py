"""Condition -> outcome tiers: validation, snapshotting and the ledger path (spec §4.6, §9).

The money arithmetic here is the risky part: ledger._insert_earn_kind is ON CONFLICT DO
NOTHING on (occurrence_id, kind), so a *changed* tier's amount would be silently swallowed
if post_tier_outcome didn't fall back to an adjustment.
"""

from __future__ import annotations

import uuid as uuidlib
from datetime import UTC, date, datetime, time

import pytest
from sqlalchemy import func, select

from app.models import Chore, ChoreOccurrence, LedgerEntry, LedgerKind, OccurrenceStatus
from app.services.ledger import balance_cents
from app.services.scheduler import generate_occurrences

pytestmark = pytest.mark.asyncio

GRADES = [
    {"id": 1, "condition": "all A grades", "outcome_kind": "money", "amount_cents": 10000},
    {"id": 2, "condition": "at least one B", "outcome_kind": "money", "amount_cents": 5000},
    {"id": 3, "condition": "at least one C", "outcome_kind": "money", "amount_cents": -5000},
]
GROUNDED = [
    {
        "id": 1,
        "condition": "more than one missing assignment",
        "outcome_kind": "text",
        "text": "grounded until it's fixed",
    }
]


async def _admin_headers(client, totp_now) -> dict:
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "parent", "password": "parent-pass", "totp_code": totp_now()},
    )
    return {"X-CSRF-Token": r.json()["csrf_token"]}


def _tiered_body(child, **over) -> dict:
    body = {
        "title": "Report card",
        "assignment_mode": "fixed",
        "fixed_assignee_id": str(child.id),
        "cadence": "monthly(day=1)",
        "due_time": "17:00:00",
        "start_date": "2025-01-01",
        "proof_type": "none",
        "verification_mode": "manual",
        "outcome_tiers": GRADES,
    }
    body.update(over)
    return body


async def _tiered_occ(db, household, child, tiers=GRADES) -> ChoreOccurrence:
    chore = Chore(
        household_id=household.id,
        title="Report card",
        assignment_mode="fixed",
        fixed_assignee_id=child.id,
        cadence="monthly(day=1)",
        due_time=time(17, 0),
        start_date=date(2025, 1, 1),
        proof_type="none",
        verification_mode="manual",
        outcome_tiers=tiers,
    )
    db.add(chore)
    await db.flush()
    occ = ChoreOccurrence(
        household_id=household.id,
        chore_id=chore.id,
        assignee_id=child.id,
        window_open_at=datetime(2025, 2, 1, 0, tzinfo=UTC),
        due_at=datetime(2025, 2, 2, 1, tzinfo=UTC),
        status=OccurrenceStatus.submitted,
        outcome_tiers=tiers,
    )
    db.add(occ)
    await db.flush()
    return occ


async def _decide(client, headers, occ_id, tier_id, reason="report card"):
    return await client.post(
        f"/api/v1/occurrences/{occ_id}/decision",
        json={"action": "tier", "tier_id": tier_id, "reason": reason},
        headers=headers,
    )


async def _entries(db, occ_id) -> list[LedgerEntry]:
    return list(
        (await db.execute(select(LedgerEntry).where(LedgerEntry.occurrence_id == occ_id)))
        .scalars()
        .all()
    )


async def _rows(db, occ_id) -> list[tuple[str, int]]:
    """(kind, amount) as a sorted multiset. created_at is the *transaction* timestamp, so
    entries written in one request all share it and no column gives a stable order."""
    return sorted((str(e.kind), e.amount_cents) for e in await _entries(db, occ_id))


# --------------------------------------------------------------------- validation


async def test_tiers_require_manual_verification(client, admin_user, child_user, totp_now):
    h = await _admin_headers(client, totp_now)
    for mode in ("llm_auto", "llm_assist", "auto_accept"):
        body = _tiered_body(child_user, verification_mode=mode)
        if mode.startswith("llm"):
            body["proof_type"] = "photo"  # LLM modes need a photo proof anyway
        r = await client.post("/api/v1/chores", json=body, headers=h)
        assert r.status_code == 422, mode
        assert "chosen by a person" in str(r.json()) or "photo proof_type" in str(r.json())


async def test_tiered_chore_must_not_also_carry_reward_or_penalty(
    client, admin_user, child_user, totp_now
):
    """Rule 4 is what makes "tiers never mix with the classic channel" enforceable."""
    h = await _admin_headers(client, totp_now)
    for over in ({"reward_cents": 100}, {"penalty_cents": 50}, {"late_multiplier": 0.5}):
        r = await client.post("/api/v1/chores", json=_tiered_body(child_user, **over), headers=h)
        assert r.status_code == 422, over
        assert "comes from its tiers" in str(r.json())


async def test_tiered_chore_rejects_an_llm_rule_or_checklist(
    client, admin_user, child_user, totp_now
):
    h = await _admin_headers(client, totp_now)
    r = await client.post(
        "/api/v1/chores",
        json=_tiered_body(
            child_user,
            verification_checklist=[{"id": 1, "text": "looks tidy?", "required": True}],
        ),
        headers=h,
    )
    assert r.status_code == 422
    assert "no LLM step" in str(r.json())


async def test_money_tier_needs_a_nonzero_amount(client, admin_user, child_user, totp_now):
    h = await _admin_headers(client, totp_now)
    for bad in (
        {"id": 1, "condition": "x", "outcome_kind": "money"},
        {"id": 1, "condition": "x", "outcome_kind": "money", "amount_cents": 0},
        {"id": 1, "condition": "x", "outcome_kind": "money", "amount_cents": 100, "text": "no"},
    ):
        r = await client.post(
            "/api/v1/chores", json=_tiered_body(child_user, outcome_tiers=[bad]), headers=h
        )
        assert r.status_code == 422, bad


async def test_text_tier_needs_text_and_no_amount(client, admin_user, child_user, totp_now):
    h = await _admin_headers(client, totp_now)
    for bad in (
        {"id": 1, "condition": "x", "outcome_kind": "text"},
        {"id": 1, "condition": "x", "outcome_kind": "text", "text": "  "},
        {"id": 1, "condition": "x", "outcome_kind": "text", "text": "ok", "amount_cents": 1},
    ):
        r = await client.post(
            "/api/v1/chores", json=_tiered_body(child_user, outcome_tiers=[bad]), headers=h
        )
        assert r.status_code == 422, bad


async def test_tier_ids_must_be_one_to_n_in_order(client, admin_user, child_user, totp_now):
    h = await _admin_headers(client, totp_now)
    tiers = [
        {"id": 1, "condition": "a", "outcome_kind": "text", "text": "x"},
        {"id": 3, "condition": "b", "outcome_kind": "text", "text": "y"},
    ]
    r = await client.post(
        "/api/v1/chores", json=_tiered_body(child_user, outcome_tiers=tiers), headers=h
    )
    assert r.status_code == 422
    assert "1..N in order" in str(r.json())


async def test_a_text_only_chore_needs_no_money_at_all(client, admin_user, child_user, totp_now):
    """The "grounded until it's fixed" case: a real chore with no money anywhere."""
    h = await _admin_headers(client, totp_now)
    r = await client.post(
        "/api/v1/chores", json=_tiered_body(child_user, outcome_tiers=GROUNDED), headers=h
    )
    assert r.status_code == 201
    assert r.json()["outcome_tiers"][0]["text"] == "grounded until it's fixed"
    assert r.json()["reward_cents"] == 0


async def test_an_untiered_chore_is_completely_unaffected(client, admin_user, child_user, totp_now):
    """Every tier rule is gated on outcome_tiers being non-empty."""
    h = await _admin_headers(client, totp_now)
    r = await client.post(
        "/api/v1/chores",
        json={
            "title": "Dishes",
            "assignment_mode": "fixed",
            "fixed_assignee_id": str(child_user.id),
            "cadence": "daily",
            "due_time": "08:00:00",
            "start_date": "2025-01-01",
            "proof_type": "photo",
            "verification_mode": "llm_auto",
            "reward_cents": 200,
            "penalty_cents": 100,
        },
        headers=h,
    )
    assert r.status_code == 201
    assert r.json()["outcome_tiers"] is None


async def test_classic_penalty_still_rejects_a_negative_value(
    client, admin_user, child_user, totp_now
):
    """reward/penalty stay unsigned magnitudes; only a tier amount is signed."""
    h = await _admin_headers(client, totp_now)
    r = await client.post(
        "/api/v1/chores",
        json={
            "title": "Dishes",
            "assignment_mode": "fixed",
            "fixed_assignee_id": str(child_user.id),
            "cadence": "daily",
            "due_time": "08:00:00",
            "start_date": "2025-01-01",
            "proof_type": "none",
            "verification_mode": "manual",
            "penalty_cents": -500,
        },
        headers=h,
    )
    assert r.status_code == 422


# --------------------------------------------------------------------- snapshotting


async def test_generated_occurrence_snapshots_the_tier_list(
    client, db_session, admin_user, child_user, totp_now
):
    h = await _admin_headers(client, totp_now)
    created = await client.post(
        "/api/v1/chores",
        json=_tiered_body(child_user, cadence="daily", start_date="2025-01-01"),
        headers=h,
    )
    assert created.status_code == 201
    await generate_occurrences(db_session)

    occ = (
        (
            await db_session.execute(
                select(ChoreOccurrence).where(
                    ChoreOccurrence.chore_id == uuidlib.UUID(created.json()["id"])
                )
            )
        )
        .scalars()
        .first()
    )
    assert occ is not None
    # stored as the validated model_dump, so absent optional keys come back explicit
    assert [(t["id"], t["condition"], t["amount_cents"]) for t in occ.outcome_tiers] == [
        (t["id"], t["condition"], t["amount_cents"]) for t in GRADES
    ]


async def test_editing_the_tiers_does_not_reprice_an_existing_occurrence(
    client, db_session, household, admin_user, child_user, totp_now
):
    """Same rule as the money snapshot (spec §3): a definition edit never rewrites history."""
    h = await _admin_headers(client, totp_now)
    occ = await _tiered_occ(db_session, household, child_user)
    await db_session.commit()

    cheaper = [dict(t, amount_cents=1) for t in GRADES]
    r = await client.patch(
        f"/api/v1/chores/{occ.chore_id}", json={"outcome_tiers": cheaper}, headers=h
    )
    assert r.status_code == 200

    assert (await _decide(client, h, occ.id, 1)).status_code == 200
    await db_session.refresh(occ)
    assert occ.outcome_tier["amount_cents"] == 10000  # the snapshot, not the new price
    assert await balance_cents(db_session, child_user.id) == 10000


# --------------------------------------------------------------------- decisions


async def test_approve_and_reject_are_refused_for_a_tiered_occurrence(
    client, db_session, household, admin_user, child_user, totp_now
):
    h = await _admin_headers(client, totp_now)
    occ = await _tiered_occ(db_session, household, child_user)
    await db_session.commit()

    for action in ("approve", "reject"):
        r = await client.post(
            f"/api/v1/occurrences/{occ.id}/decision",
            json={"action": action, "reason": "nope"},
            headers=h,
        )
        assert r.status_code == 409
        assert "outcome tier" in r.json()["detail"]


async def test_positive_tier_writes_an_earning(
    client, db_session, household, admin_user, child_user, totp_now
):
    h = await _admin_headers(client, totp_now)
    occ = await _tiered_occ(db_session, household, child_user)
    await db_session.commit()

    assert (await _decide(client, h, occ.id, 1)).status_code == 200
    await db_session.refresh(occ)

    assert occ.status == OccurrenceStatus.approved
    assert occ.outcome_tier_id == 1
    assert occ.outcome_tier["condition"] == "all A grades"
    assert await _rows(db_session, occ.id) == [(LedgerKind.earning, 10000)]
    assert await balance_cents(db_session, child_user.id) == 10000


async def test_negative_tier_writes_a_penalty_stored_signed(
    client, db_session, household, admin_user, child_user, totp_now
):
    """A tier amount is already signed, so it is stored as-is — never re-abs()'d."""
    h = await _admin_headers(client, totp_now)
    occ = await _tiered_occ(db_session, household, child_user)
    await db_session.commit()

    assert (await _decide(client, h, occ.id, 3)).status_code == 200

    assert await _rows(db_session, occ.id) == [(LedgerKind.penalty, -5000)]
    assert await balance_cents(db_session, child_user.id) == -5000


async def test_text_tier_writes_no_ledger_entry(
    client, db_session, household, admin_user, child_user, totp_now
):
    h = await _admin_headers(client, totp_now)
    occ = await _tiered_occ(db_session, household, child_user, tiers=GROUNDED)
    await db_session.commit()

    assert (await _decide(client, h, occ.id, 1)).status_code == 200
    await db_session.refresh(occ)

    assert occ.status == OccurrenceStatus.approved
    assert occ.outcome_tier["text"] == "grounded until it's fixed"
    assert await _entries(db_session, occ.id) == []
    assert await balance_cents(db_session, child_user.id) == 0


async def test_changing_the_tier_reverses_and_nets_correctly(
    client, db_session, household, admin_user, child_user, totp_now
):
    """+$50 then re-graded to -$50. The earning slot is taken, so the reversal and the new
    amount are both adjustments — nothing is UPDATEd and the balance is right."""
    h = await _admin_headers(client, totp_now)
    occ = await _tiered_occ(db_session, household, child_user)
    await db_session.commit()

    assert (await _decide(client, h, occ.id, 2)).status_code == 200
    assert await balance_cents(db_session, child_user.id) == 5000

    assert (await _decide(client, h, occ.id, 3, reason="miscounted")).status_code == 200
    await db_session.refresh(occ)

    entries = await _entries(db_session, occ.id)
    assert await _rows(db_session, occ.id) == sorted(
        [
            (LedgerKind.earning, 5000),
            (LedgerKind.adjustment, -5000),  # reversal of the first tier
            (LedgerKind.penalty, -5000),  # the new tier: the penalty slot was still free
        ]
    )
    earning = next(e for e in entries if str(e.kind) == LedgerKind.earning)
    reversal = next(e for e in entries if str(e.kind) == LedgerKind.adjustment)
    assert earning.reversed_by_entry_id == reversal.id
    assert occ.outcome_tier_id == 3
    assert await balance_cents(db_session, child_user.id) == -5000


async def test_changing_between_two_positive_tiers_uses_an_adjustment(
    client, db_session, household, admin_user, child_user, totp_now
):
    """The case that would silently keep the old amount: the earning slot is already taken,
    so ON CONFLICT DO NOTHING would swallow the new one."""
    h = await _admin_headers(client, totp_now)
    occ = await _tiered_occ(db_session, household, child_user)
    await db_session.commit()

    assert (await _decide(client, h, occ.id, 1)).status_code == 200  # +100.00
    assert (await _decide(client, h, occ.id, 2)).status_code == 200  # -> +50.00

    assert await _rows(db_session, occ.id) == sorted(
        [
            (LedgerKind.earning, 10000),
            (LedgerKind.adjustment, -10000),  # reversal
            (LedgerKind.adjustment, 5000),  # the new amount: the earning slot was taken
        ]
    )
    entries = await _entries(db_session, occ.id)
    assert any(e.meta == {"tier_id": 2} for e in entries)
    assert await balance_cents(db_session, child_user.id) == 5000


async def test_picking_the_same_tier_twice_is_a_noop(
    client, db_session, household, admin_user, child_user, totp_now
):
    h = await _admin_headers(client, totp_now)
    occ = await _tiered_occ(db_session, household, child_user)
    await db_session.commit()

    assert (await _decide(client, h, occ.id, 1)).status_code == 200
    assert (await _decide(client, h, occ.id, 1)).status_code == 200

    assert len(await _entries(db_session, occ.id)) == 1
    assert await balance_cents(db_session, child_user.id) == 10000


async def test_excuse_reverses_the_money_and_clears_the_tier(
    client, db_session, household, admin_user, child_user, totp_now
):
    """Clearing matters: otherwise re-picking that same tier would hit the no-op guard and
    the money would never come back."""
    h = await _admin_headers(client, totp_now)
    occ = await _tiered_occ(db_session, household, child_user)
    await db_session.commit()

    assert (await _decide(client, h, occ.id, 1)).status_code == 200
    r = await client.post(
        f"/api/v1/occurrences/{occ.id}/decision",
        json={"action": "excuse", "reason": "sick"},
        headers=h,
    )
    assert r.status_code == 200
    await db_session.refresh(occ)
    assert occ.outcome_tier_id is None and occ.outcome_tier is None
    assert await balance_cents(db_session, child_user.id) == 0

    # re-grading after an excuse pays again
    assert (await _decide(client, h, occ.id, 1)).status_code == 200
    assert await balance_cents(db_session, child_user.id) == 10000


async def test_unknown_tier_id_is_rejected(
    client, db_session, household, admin_user, child_user, totp_now
):
    h = await _admin_headers(client, totp_now)
    occ = await _tiered_occ(db_session, household, child_user)
    await db_session.commit()

    r = await _decide(client, h, occ.id, 99)
    assert r.status_code == 409
    assert "not one of this chore's outcomes" in r.json()["detail"]


async def test_tier_on_a_settlement_locked_occurrence_is_refused(
    client, db_session, household, admin_user, child_user, totp_now
):
    h = await _admin_headers(client, totp_now)
    occ = await _tiered_occ(db_session, household, child_user)
    occ.settlement_locked_at = datetime(2025, 3, 1, tzinfo=UTC)
    await db_session.commit()

    assert (await _decide(client, h, occ.id, 1)).status_code == 409


async def test_tier_action_needs_a_tier_id(
    client, db_session, household, admin_user, child_user, totp_now
):
    h = await _admin_headers(client, totp_now)
    occ = await _tiered_occ(db_session, household, child_user)
    await db_session.commit()

    r = await client.post(
        f"/api/v1/occurrences/{occ.id}/decision",
        json={"action": "tier", "reason": "x"},
        headers=h,
    )
    assert r.status_code == 422


async def test_tier_id_is_rejected_for_a_non_tier_action(
    client, db_session, household, admin_user, child_user, totp_now
):
    h = await _admin_headers(client, totp_now)
    occ = await _tiered_occ(db_session, household, child_user)
    await db_session.commit()

    r = await client.post(
        f"/api/v1/occurrences/{occ.id}/decision",
        json={"action": "excuse", "reason": "x", "tier_id": 1},
        headers=h,
    )
    assert r.status_code == 422


async def test_tier_decision_is_visible_on_the_occurrence(
    client, db_session, household, admin_user, child_user, totp_now
):
    """The kid has to be able to see which condition was met — that is the whole point."""
    h = await _admin_headers(client, totp_now)
    occ = await _tiered_occ(db_session, household, child_user)
    await db_session.commit()

    assert (await _decide(client, h, occ.id, 2)).status_code == 200
    body = (await client.get(f"/api/v1/occurrences/{occ.id}", headers=h)).json()
    assert body["outcome_tier_id"] == 2
    assert body["outcome_tier"]["condition"] == "at least one B"
    assert len(body["outcome_tiers"]) == 3


async def test_a_tiered_occurrence_writes_one_audit_row_per_decision(
    client, db_session, household, admin_user, child_user, totp_now
):
    from app.models import AuditLog

    h = await _admin_headers(client, totp_now)
    occ = await _tiered_occ(db_session, household, child_user)
    await db_session.commit()

    await _decide(client, h, occ.id, 1)
    n = await db_session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.action == "occurrence.decision.tier")
    )
    assert n == 1
