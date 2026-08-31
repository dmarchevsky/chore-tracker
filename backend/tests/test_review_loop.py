"""Phase 3 acceptance: the manual verification loop end to end (spec §14 Phase 3)."""

from __future__ import annotations

import io
from datetime import UTC, date, datetime, time

import pytest
from PIL import Image
from sqlalchemy import func, select

from app.models import Chore, ChoreOccurrence, LedgerEntry, OccurrenceStatus
from app.services.ledger import balance_cents

pytestmark = pytest.mark.asyncio


def _jpeg(color=(30, 160, 60)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (640, 480), color).save(buf, format="JPEG", quality=90)
    return buf.getvalue()


async def _mk_occ(
    db,
    household,
    child,
    *,
    mode="manual",
    reward=200,
    penalty=0,
    proof="photo",
    allow_gallery=False,
    geofence=None,
    st=OccurrenceStatus.open,
) -> ChoreOccurrence:
    chore = Chore(
        household_id=household.id,
        title="Kitchen",
        assignment_mode="fixed",
        fixed_assignee_id=child.id,
        cadence="daily",
        due_time=time(8, 0),
        start_date=date(2025, 1, 1),
        proof_type=proof,
        photo_count=1,
        photo_prompts=["sink"],
        allow_gallery_upload=allow_gallery,
        geofence=geofence,
        verification_mode=mode,
        reward_cents=reward,
        penalty_cents=penalty,
    )
    db.add(chore)
    await db.flush()
    occ = ChoreOccurrence(
        household_id=household.id,
        chore_id=chore.id,
        assignee_id=child.id,
        window_open_at=datetime(2025, 1, 2, 0, tzinfo=UTC),
        due_at=datetime(2025, 1, 2, 16, tzinfo=UTC),
        status=st,
        reward_cents=reward,
        penalty_cents=penalty,
    )
    db.add(occ)
    await db.flush()
    return occ


async def _kid_login(client):
    r = await client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "alice-pass"}
    )
    return {"X-CSRF-Token": r.json()["csrf_token"]}


async def _admin_login(client, totp_now):
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "parent", "password": "parent-pass", "totp_code": totp_now()},
    )
    return {"X-CSRF-Token": r.json()["csrf_token"]}


async def _submit_photo(client, occ_id, headers, *, source="camera"):
    return await client.post(
        f"/api/v1/occurrences/{occ_id}/submissions",
        files=[("files", ("sink.jpg", _jpeg(), "image/jpeg"))],
        data={"note": "all done", "source": source},
        headers=headers,
    )


async def _ledger_rows(db, occ_id) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(LedgerEntry).where(LedgerEntry.occurrence_id == occ_id)
        )
    ).scalar_one()


async def test_manual_loop_photo_to_approve_credits_once(
    client, db_session, household, admin_user, child_user, totp_now
):
    occ = await _mk_occ(db_session, household, child_user, reward=250)
    await db_session.commit()

    kh = await _kid_login(client)
    r = await _submit_photo(client, occ.id, kh)
    assert r.status_code == 201, r.text
    assert r.json()["media"][0]["url"].startswith("/api/v1/submissions/")

    await db_session.refresh(occ)
    assert occ.status == OccurrenceStatus.submitted

    ah = await _admin_login(client, totp_now)
    inbox = (await client.get("/api/v1/occurrences?inbox=true", headers=ah)).json()
    assert str(occ.id) in [o["id"] for o in inbox]

    dec = await client.post(
        f"/api/v1/occurrences/{occ.id}/decision",
        json={"action": "approve", "reason": "looks clean"},
        headers=ah,
    )
    assert dec.status_code == 200 and dec.json()["status"] == "approved"
    assert await balance_cents(db_session, child_user.id) == 250
    assert await _ledger_rows(db_session, occ.id) == 1


async def test_double_approve_does_not_double_pay(
    client, db_session, household, admin_user, child_user, totp_now
):
    occ = await _mk_occ(db_session, household, child_user, reward=300)
    await db_session.commit()
    kh = await _kid_login(client)
    await _submit_photo(client, occ.id, kh)

    ah = await _admin_login(client, totp_now)
    body = {"action": "approve", "reason": "ok"}
    a = await client.post(f"/api/v1/occurrences/{occ.id}/decision", json=body, headers=ah)
    b = await client.post(f"/api/v1/occurrences/{occ.id}/decision", json=body, headers=ah)
    assert a.status_code == 200 and b.status_code == 200

    assert await balance_cents(db_session, child_user.id) == 300
    assert await _ledger_rows(db_session, occ.id) == 1


async def test_amount_override(client, db_session, household, admin_user, child_user, totp_now):
    occ = await _mk_occ(db_session, household, child_user, reward=250)
    await db_session.commit()
    await _submit_photo(client, occ.id, await _kid_login(client))
    ah = await _admin_login(client, totp_now)
    await client.post(
        f"/api/v1/occurrences/{occ.id}/decision",
        json={"action": "approve", "reason": "half - only did part", "amount_override_cents": 120},
        headers=ah,
    )
    assert await balance_cents(db_session, child_user.id) == 120


async def test_reject_applies_penalty(
    client, db_session, household, admin_user, child_user, totp_now
):
    occ = await _mk_occ(db_session, household, child_user, reward=200, penalty=100)
    await db_session.commit()
    await _submit_photo(client, occ.id, await _kid_login(client))
    ah = await _admin_login(client, totp_now)
    r = await client.post(
        f"/api/v1/occurrences/{occ.id}/decision",
        json={"action": "reject", "reason": "still dishes in the sink"},
        headers=ah,
    )
    assert r.json()["status"] == "rejected"
    assert await balance_cents(db_session, child_user.id) == -100


async def test_auto_accept_credits_immediately(
    client, db_session, household, admin_user, child_user, totp_now
):
    occ = await _mk_occ(db_session, household, child_user, mode="auto_accept", reward=150)
    await db_session.commit()
    r = await _submit_photo(client, occ.id, await _kid_login(client))
    assert r.status_code == 201
    await db_session.refresh(occ)
    assert occ.status == OccurrenceStatus.verified_pass
    assert await balance_cents(db_session, child_user.id) == 150


async def test_gallery_upload_rules(
    client, db_session, household, admin_user, child_user, totp_now
):
    blocked = await _mk_occ(db_session, household, child_user, allow_gallery=False)
    allowed = await _mk_occ(
        db_session,
        household,
        child_user,
        allow_gallery=True,
        st=OccurrenceStatus.open,
    )
    await db_session.commit()
    kh = await _kid_login(client)

    r1 = await _submit_photo(client, blocked.id, kh, source="gallery")
    assert r1.status_code == 422

    r2 = await _submit_photo(client, allowed.id, kh, source="gallery")
    assert r2.status_code == 201
    assert "GALLERY_UPLOAD" in r2.json()["flags"]
    await db_session.refresh(allowed)
    assert allowed.status == OccurrenceStatus.needs_review


async def test_cannot_submit_to_terminal_occurrence(
    client, db_session, household, admin_user, child_user, totp_now
):
    occ = await _mk_occ(db_session, household, child_user, st=OccurrenceStatus.missed)
    await db_session.commit()
    r = await _submit_photo(client, occ.id, await _kid_login(client))
    assert r.status_code == 409


async def test_media_served_only_with_auth_or_signature(
    client, db_session, household, admin_user, child_user, totp_now
):
    occ = await _mk_occ(db_session, household, child_user)
    await db_session.commit()
    kh = await _kid_login(client)
    sub = (await _submit_photo(client, occ.id, kh)).json()
    signed_url = sub["media"][0]["url"]
    path = signed_url.split("?")[0]

    # Owning kid (session, no signature) can fetch.
    assert (await client.get(path)).status_code == 200

    # Drop the session: the signature alone still works, a tampered one does not.
    client.cookies.clear()
    assert (await client.get(signed_url)).status_code == 200
    bad = signed_url.rsplit("sig=", 1)[0] + "sig=deadbeefdeadbeefdeadbeefdeadbeef"
    assert (await client.get(bad)).status_code == 403
    # No session and no signature -> refused.
    assert (await client.get(path)).status_code == 403


async def test_settlement_locked_blocks_decision(
    client, db_session, household, admin_user, child_user, totp_now
):
    occ = await _mk_occ(db_session, household, child_user)
    occ.settlement_locked_at = datetime(2025, 2, 1, tzinfo=UTC)
    await db_session.commit()
    ah = await _admin_login(client, totp_now)
    r = await client.post(
        f"/api/v1/occurrences/{occ.id}/decision",
        json={"action": "approve", "reason": "too late"},
        headers=ah,
    )
    assert r.status_code == 409


async def test_rejection_reason_reaches_the_kid_and_nothing_else_does(
    client, db_session, household, admin_user, child_user, totp_now
):
    """A decision the kid can't see the reasoning for is just a number moving
    (spec §6.3 rule 1) — but confidence and flags stay admin-only (spec §11)."""
    occ = await _mk_occ(db_session, household, child_user, reward=200, penalty=50)
    await db_session.commit()

    kh = await _kid_login(client)
    await _submit_photo(client, occ.id, kh)

    ah = await _admin_login(client, totp_now)
    await client.post(
        f"/api/v1/occurrences/{occ.id}/decision",
        json={"action": "reject", "reason": "the sink is still full"},
        headers=ah,
    )

    kh = await _kid_login(client)
    seen = (await client.get(f"/api/v1/occurrences/{occ.id}/verifications", headers=kh)).json()
    assert seen[0]["child_message"] == "the sink is still full"
    assert seen[0]["kind"] == "manual"  # so the app can say "from a parent"
    assert "confidence" not in seen[0] and "reasoning" not in seen[0]

    ah = await _admin_login(client, totp_now)  # one cookie jar per client
    admin_view = (
        await client.get(f"/api/v1/occurrences/{occ.id}/verifications", headers=ah)
    ).json()
    assert admin_view[0]["reasoning"] == "the sink is still full"
