"""Phase 6: household export and restore — a backup must reproduce balances exactly."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from tests.helpers import sign_in

from app.models import (
    Chore,
    ChoreOccurrence,
    Dispute,
    HouseholdSettings,
    LedgerEntry,
    OccurrenceStatus,
    Submission,
    SubmissionMedia,
    User,
    Verification,
)
from app.services.export import ExportError, _coerce, validate_bundle
from app.services.ledger import balance_cents, credit_earning, reverse_entry

pytestmark = pytest.mark.asyncio


async def _admin_headers(client) -> dict:
    r = await sign_in(client, "parent@example.com")
    assert r.status_code == 200
    return {"X-CSRF-Token": r.json()["csrf_token"]}


@pytest.fixture
def _seed():
    """Build one of everything so the round trip has every table to carry."""

    async def build(db, household, admin_user, child_user) -> ChoreOccurrence:
        db.add(
            HouseholdSettings(
                household_id=household.id,
                llm_base_url="http://vision.local",
                llm_api_key="super-secret",
                auto_pass_threshold=Decimal("0.90"),
                updated_by_user_id=admin_user.id,
            )
        )
        chore = Chore(
            household_id=household.id,
            title="Kitchen",
            assignment_mode="rotating",
            assignee_ids=[child_user.id],
            cadence="daily",
            due_time=time(8, 0),
            start_date=date(2025, 1, 1),
            proof_type="photo",
            photo_count=1,
            photo_prompts=["the sink"],
            verification_mode="manual",
            reward_cents=250,
            penalty_cents=100,
            late_multiplier=Decimal("0.50"),
        )
        db.add(chore)
        await db.flush()

        occ = ChoreOccurrence(
            household_id=household.id,
            chore_id=chore.id,
            assignee_id=child_user.id,
            window_open_at=datetime(2025, 1, 2, tzinfo=UTC),
            due_at=datetime(2025, 1, 2, 16, tzinfo=UTC),
            status=OccurrenceStatus.approved,
            reward_cents=250,
        )
        db.add(occ)
        await db.flush()

        sub = Submission(
            occurrence_id=occ.id,
            submitter_id=child_user.id,
            kind="photo",
            source="camera",
            note="done",
        )
        db.add(sub)
        await db.flush()
        db.add(
            SubmissionMedia(
                submission_id=sub.id,
                idx=0,
                sha256="a" * 64,
                storage_path="hh/2025/01/aa/aaaa.jpg",
                mime="image/jpeg",
                width=320,
                height=240,
                bytes=1234,
            )
        )
        db.add(
            Verification(
                occurrence_id=occ.id,
                submission_id=sub.id,
                kind="manual",
                verdict="pass",
                actor_user_id=admin_user.id,
            )
        )
        db.add(
            Dispute(
                occurrence_id=occ.id,
                author_user_id=child_user.id,
                message="it was clean",
                status_at_filing=OccurrenceStatus.approved,
            )
        )

        earning = await credit_earning(db, occurrence=occ)
        await reverse_entry(db, entry=earning, actor=admin_user, reason="counted twice")
        await db.commit()
        return occ

    return build


async def _export(client, headers, *, history=True, money=True) -> dict:
    r = await client.get(
        f"/api/v1/admin/export?history={str(history).lower()}&money={str(money).lower()}",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert "attachment" in r.headers["content-disposition"]
    return json.loads(r.text)


async def _count(db, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def test_round_trip_reproduces_balances(
    client, db_session, household, admin_user, child_user, _seed
):
    await _seed(db_session, household, admin_user, child_user)
    headers = await _admin_headers(client)
    child_id = child_user.id
    before_balance = await balance_cents(db_session, child_id)
    before_counts = {m: await _count(db_session, m) for m in (User, Chore, ChoreOccurrence)}
    assert before_balance == 0  # earning reversed

    bundle = await _export(client, headers)
    r = await client.post("/api/v1/admin/import", json={"bundle": bundle}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counts"]["ledger_entries"] == 2
    assert body["csrf_token"]

    db_session.expunge_all()
    assert await balance_cents(db_session, child_id) == before_balance
    assert {m: await _count(db_session, m) for m in (User, Chore, ChoreOccurrence)} == before_counts
    # The reversal self-FK is restored, not dropped.
    original = (
        await db_session.execute(select(LedgerEntry).where(LedgerEntry.kind == "earning"))
    ).scalar_one()
    assert original.reversed_by_entry_id is not None
    # Chore definitions survive intact, arrays and decimals included.
    chore = (await db_session.execute(select(Chore))).scalar_one()
    assert chore.assignee_ids == [child_id]
    assert chore.photo_prompts == ["the sink"]
    assert Decimal(str(chore.late_multiplier)) == Decimal("0.50")
    # The caller is still signed in on the freshly minted session.
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["role"] == "admin"


async def test_toggles_choose_what_travels(
    client, db_session, household, admin_user, child_user, _seed
):
    await _seed(db_session, household, admin_user, child_user)
    headers = await _admin_headers(client)

    definitions = await _export(client, headers, history=False, money=False)
    assert set(definitions["tables"]) == {"households", "users", "household_settings", "chores"}

    with_money = await _export(client, headers, history=False, money=True)
    assert "chore_occurrences" not in with_money["tables"]
    entries = with_money["tables"]["ledger_entries"]
    assert entries and all(e["occurrence_id"] is None for e in entries)
    assert any("lost their link" in w for w in with_money["warnings"])

    with_history = await _export(client, headers, history=True, money=False)
    assert "ledger_entries" not in with_history["tables"]
    assert with_history["counts"]["submission_media"] == 1


async def test_money_without_history_still_restores_balances(
    client, db_session, household, admin_user, child_user, _seed
):
    await _seed(db_session, household, admin_user, child_user)
    child_id = child_user.id
    headers = await _admin_headers(client)
    bundle = await _export(client, headers, history=False, money=True)

    r = await client.post("/api/v1/admin/import", json={"bundle": bundle}, headers=headers)
    assert r.status_code == 200, r.text

    db_session.expunge_all()
    assert await balance_cents(db_session, child_id) == 0
    assert await _count(db_session, LedgerEntry) == 2
    assert await _count(db_session, ChoreOccurrence) == 0


async def test_export_carries_no_secrets(
    client, db_session, household, admin_user, child_user, _seed
):
    await _seed(db_session, household, admin_user, child_user)
    headers = await _admin_headers(client)
    r = await client.get("/api/v1/admin/export", headers=headers)

    assert "super-secret" not in r.text
    assert "llm_api_key" not in r.text
    assert "password_hash" not in r.text
    tables = json.loads(r.text)["tables"]
    for excluded in ("sessions", "checkin_tokens", "push_subscriptions", "verification_jobs"):
        assert excluded not in tables


async def test_import_refuses_a_bundle_that_would_lock_the_parent_out(
    client, db_session, household, admin_user, child_user, _seed
):
    await _seed(db_session, household, admin_user, child_user)
    headers = await _admin_headers(client)
    bundle = await _export(client, headers)
    for row in bundle["tables"]["users"]:
        if row["role"] == "admin":
            row["email"] = "someone-else@example.com"

    r = await client.post("/api/v1/admin/import", json={"bundle": bundle}, headers=headers)
    assert r.status_code == 400
    assert "lock you out" in r.json()["detail"]

    db_session.expunge_all()
    assert await _count(db_session, Chore) == 1  # nothing was wiped


async def test_dry_run_writes_nothing(client, db_session, household, admin_user, child_user, _seed):
    await _seed(db_session, household, admin_user, child_user)
    headers = await _admin_headers(client)
    bundle = await _export(client, headers)
    bundle["tables"]["chores"] = []

    r = await client.post(
        "/api/v1/admin/import", json={"bundle": bundle, "dry_run": True}, headers=headers
    )
    assert r.status_code == 200
    assert r.json()["dry_run"] is True
    assert r.json()["counts"]["chores"] == 0
    assert any("break-glass" in w for w in r.json()["warnings"])

    db_session.expunge_all()
    assert await _count(db_session, Chore) == 1


async def test_a_child_may_not_export_or_import(client, db_session, admin_user, child_user):
    r = await sign_in(client, "alice@example.com")
    assert r.status_code == 200
    headers = {"X-CSRF-Token": r.json()["csrf_token"]}

    assert (await client.get("/api/v1/admin/export", headers=headers)).status_code == 403
    resp = await client.post("/api/v1/admin/import", json={"bundle": {}}, headers=headers)
    assert resp.status_code == 403


async def test_bad_bundles_are_rejected(admin_user):
    with pytest.raises(ExportError, match="version"):
        validate_bundle({"version": 99, "tables": {}}, actor=admin_user)
    with pytest.raises(ExportError, match="does not know"):
        validate_bundle({"version": 1, "tables": {"sessions": []}}, actor=admin_user)
    with pytest.raises(ExportError, match="missing required"):
        validate_bundle({"version": 1, "tables": {"households": []}}, actor=admin_user)


async def test_coerce_rebuilds_awkward_column_types():
    child = uuid.uuid4()
    row = _coerce(
        Chore,
        {
            "id": str(uuid.uuid4()),
            "assignee_ids": [str(child)],
            "due_time": "08:00:00",
            "start_date": "2025-01-01",
            "late_multiplier": "0.50",
            "created_at": "2025-01-01T00:00:00+00:00",
            "geofence": {"lat": 1.0},
        },
    )
    assert row["assignee_ids"] == [child]
    assert row["due_time"] == time(8, 0)
    assert row["start_date"] == date(2025, 1, 1)
    assert row["late_multiplier"] == Decimal("0.50")
    assert row["created_at"] == datetime(2025, 1, 1, tzinfo=UTC)
    assert row["geofence"] == {"lat": 1.0}

    with pytest.raises(ExportError, match="unknown column"):
        _coerce(Chore, {"nope": 1})
