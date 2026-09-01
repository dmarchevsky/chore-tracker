"""Phase 3: balances, ledger statements (CSV), and payouts (spec §4.3, §9)."""

from __future__ import annotations

import io
from datetime import UTC, date, datetime, time

import pytest
from PIL import Image

from app.models import Chore, ChoreOccurrence, OccurrenceStatus
from app.services.settlement import settle_missed

pytestmark = pytest.mark.asyncio


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (320, 240), (40, 120, 200)).save(buf, format="JPEG")
    return buf.getvalue()


async def _open_occ(db, household, child, reward=200) -> ChoreOccurrence:
    chore = Chore(
        household_id=household.id,
        title="Kitchen",
        assignment_mode="fixed",
        fixed_assignee_id=child.id,
        cadence="daily",
        due_time=time(8, 0),
        start_date=date(2025, 1, 1),
        proof_type="photo",
        photo_count=1,
        verification_mode="manual",
        reward_cents=reward,
    )
    db.add(chore)
    await db.flush()
    occ = ChoreOccurrence(
        household_id=household.id,
        chore_id=chore.id,
        assignee_id=child.id,
        window_open_at=datetime(2025, 1, 2, tzinfo=UTC),
        due_at=datetime(2025, 1, 2, 16, tzinfo=UTC),
        status=OccurrenceStatus.open,
        reward_cents=reward,
    )
    db.add(occ)
    await db.flush()
    return occ


async def _admin(client, totp_now) -> dict:
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "parent", "password": "parent-pass", "totp_code": totp_now()},
    )
    return {"X-CSRF-Token": r.json()["csrf_token"]}


async def _earn(client, db, household, admin_user, child_user, headers, reward):
    occ = await _open_occ(db, household, child_user, reward)
    await db.commit()
    login = await client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "alice-pass"}
    )
    await client.post(
        f"/api/v1/occurrences/{occ.id}/submissions",
        files=[("files", ("a.jpg", _jpeg(), "image/jpeg"))],
        data={"source": "camera"},
        headers={"X-CSRF-Token": login.json()["csrf_token"]},
    )
    h = await _admin(client, headers)  # re-login mints a fresh CSRF token
    await client.post(
        f"/api/v1/occurrences/{occ.id}/decision",
        json={"action": "approve", "reason": "ok"},
        headers=h,
    )
    return h


async def test_balance_and_ledger_and_csv(
    client, db_session, household, admin_user, child_user, totp_now
):
    h = await _earn(client, db_session, household, admin_user, child_user, totp_now, 250)

    bal = await client.get(f"/api/v1/children/{child_user.id}/balance", headers=h)
    assert bal.status_code == 200 and bal.json()["balance_cents"] == 250

    led = await client.get(f"/api/v1/children/{child_user.id}/ledger", headers=h)
    assert [e["kind"] for e in led.json()] == ["earning"]

    csv_resp = await client.get(f"/api/v1/children/{child_user.id}/ledger.csv", headers=h)
    assert csv_resp.headers["content-type"].startswith("text/csv")
    assert "earning" in csv_resp.text and "250" in csv_resp.text


async def test_the_statement_names_the_chore_each_entry_was_for(
    client, db_session, household, admin_user, child_user, totp_now
):
    """ "chore missed" alone doesn't say which chore — the statement carries the title and
    the day it was due (spec §4.3)."""
    h = await _earn(client, db_session, household, admin_user, child_user, totp_now, 250)
    await client.post(
        "/api/v1/payouts",
        json={"child_id": str(child_user.id), "amount_cents": 250, "method": "cash"},
        headers=h,
    )

    led = (await client.get(f"/api/v1/children/{child_user.id}/ledger", headers=h)).json()
    earning = next(e for e in led if e["kind"] == "earning")
    assert earning["chore_title"] == "Kitchen"
    assert earning["occurrence_due_at"].startswith("2025-01-02")

    # A payout has no occurrence behind it, so there is no chore to name.
    payout = next(e for e in led if e["kind"] == "payout")
    assert payout["chore_title"] is None and payout["occurrence_due_at"] is None

    csv_resp = await client.get(f"/api/v1/children/{child_user.id}/ledger.csv", headers=h)
    assert "chore" in csv_resp.text.splitlines()[0]
    assert "Kitchen" in csv_resp.text


async def test_a_penalty_can_be_excused_from_the_statement(
    client, db_session, household, admin_user, child_user, totp_now
):
    """The statement links back to the occurrence, so the fix is the ordinary decision path
    — a reversing entry, never a deleted row (spec §9)."""
    occ = await _open_occ(db_session, household, child_user, 200)
    occ.penalty_cents = 500
    occ.status = OccurrenceStatus.missed
    await db_session.commit()
    await settle_missed(db_session, now=datetime(2025, 1, 3, tzinfo=UTC))
    await db_session.commit()

    h = await _admin(client, totp_now)
    led = (await client.get(f"/api/v1/children/{child_user.id}/ledger", headers=h)).json()
    penalty = next(e for e in led if e["kind"] == "penalty")
    assert penalty["chore_title"] == "Kitchen"
    assert penalty["occurrence_id"] == str(occ.id)
    assert penalty["reversed_by_entry_id"] is None

    r = await client.post(
        f"/api/v1/occurrences/{penalty['occurrence_id']}/decision",
        json={"action": "excuse", "reason": "we were away"},
        headers=h,
    )
    assert r.status_code == 200

    after = (await client.get(f"/api/v1/children/{child_user.id}/ledger", headers=h)).json()
    assert next(e for e in after if e["id"] == penalty["id"])["reversed_by_entry_id"] is not None
    bal = await client.get(f"/api/v1/children/{child_user.id}/balance", headers=h)
    assert bal.json()["balance_cents"] == 0


async def test_child_sees_own_balance_but_not_siblings(
    client, db_session, household, admin_user, child_user, totp_now
):
    await _earn(client, db_session, household, admin_user, child_user, totp_now, 100)

    await client.post("/api/v1/auth/login", json={"username": "alice", "password": "alice-pass"})
    mine = await client.get(f"/api/v1/children/{child_user.id}/balance")
    assert mine.status_code == 200 and mine.json()["balance_cents"] == 100

    other = await client.get(f"/api/v1/children/{admin_user.id}/balance")
    assert other.status_code in (403, 404)


async def test_payout_writes_negative_entry_and_zeros_balance(
    client, db_session, household, admin_user, child_user, totp_now
):
    h = await _earn(client, db_session, household, admin_user, child_user, totp_now, 500)

    pay = await client.post(
        "/api/v1/payouts",
        json={
            "child_id": str(child_user.id),
            "amount_cents": 500,
            "method": "cash",
            "note": "allowance",
            "covers_through": "2025-01-31",
        },
        headers=h,
    )
    assert pay.status_code == 201
    assert pay.json()["kind"] == "payout" and pay.json()["amount_cents"] == -500

    bal = await client.get(f"/api/v1/children/{child_user.id}/balance", headers=h)
    assert bal.json()["balance_cents"] == 0

    listing = await client.get(f"/api/v1/payouts?child_id={child_user.id}", headers=h)
    assert len(listing.json()) == 1


async def test_negative_balance_is_allowed(
    client, db_session, household, admin_user, child_user, totp_now
):
    h = await _admin(client, totp_now)
    r = await client.post(
        "/api/v1/payouts",
        json={"child_id": str(child_user.id), "amount_cents": 100, "method": "cash", "note": ""},
        headers=h,
    )
    assert r.status_code == 201
    bal = await client.get(f"/api/v1/children/{child_user.id}/balance", headers=h)
    assert bal.json()["balance_cents"] == -100  # spec §15 Q3: allow negative
