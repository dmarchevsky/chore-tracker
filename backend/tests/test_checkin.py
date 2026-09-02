"""Phase 5: per-kid geofence check-in webhook (spec §6.2)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

import pytest
from sqlalchemy import func, select
from tests.helpers import sign_in

from app.auth import ratelimit
from app.models import Chore, ChoreOccurrence, LedgerEntry, OccurrenceStatus, Submission

pytestmark = pytest.mark.asyncio

SCHOOL = {"lat": 37.7749, "lon": -122.4194, "radius_m": 120, "arrive_before": "08:10"}
AT_SCHOOL = {"lat": 37.7749, "lon": -122.4194, "accuracy": 15}
FAR_AWAY = {"lat": 37.8100, "lon": -122.4100, "accuracy": 15}
FUZZY = {"lat": 37.7749, "lon": -122.4194, "accuracy": 250}


async def _admin(client) -> dict:
    r = await sign_in(client, "parent@example.com")
    return {"X-CSRF-Token": r.json()["csrf_token"]}


async def _location_occ(db, household, child, *, mode="auto_accept", reward=100) -> ChoreOccurrence:
    chore = Chore(
        household_id=household.id,
        title="Check in at school",
        assignment_mode="fixed",
        fixed_assignee_id=child.id,
        cadence="weekdays",
        due_time=time(8, 5),
        start_date=date(2025, 1, 1),
        proof_type="location",
        photo_count=0,
        geofence=SCHOOL,
        verification_mode=mode,
        reward_cents=reward,
    )
    db.add(chore)
    await db.flush()
    occ = ChoreOccurrence(
        household_id=household.id,
        chore_id=chore.id,
        assignee_id=child.id,
        window_open_at=datetime(2025, 1, 2, 12, tzinfo=UTC),
        due_at=datetime(2025, 1, 2, 16, tzinfo=UTC),
        status=OccurrenceStatus.open,
        reward_cents=reward,
    )
    db.add(occ)
    await db.flush()
    return occ


async def _token(client, admin_user, child_user) -> str:
    h = await _admin(client)
    r = await client.get(f"/api/v1/children/{child_user.id}/checkin-token", headers=h)
    assert r.status_code == 200
    assert r.json()["webhook_url"].endswith(r.json()["token"])
    assert r.json()["stale"] is True  # never used
    return r.json()["token"]


async def test_unknown_token_is_404(client):
    r = await client.post("/api/v1/checkin/nope", json=AT_SCHOOL)
    assert r.status_code == 404


async def test_checkin_with_no_open_occurrence(client, admin_user, child_user):
    tok = await _token(client, admin_user, child_user)
    r = await client.post(f"/api/v1/checkin/{tok}", json=AT_SCHOOL)
    assert r.status_code == 200 and r.json()["matched"] is False


async def test_checkin_inside_fence_passes_and_credits(
    client, db_session, household, admin_user, child_user
):
    occ = await _location_occ(db_session, household, child_user)
    await db_session.commit()
    tok = await _token(client, admin_user, child_user)

    r = await client.post(f"/api/v1/checkin/{tok}", json=AT_SCHOOL)
    body = r.json()
    assert body["matched"] and body["within"] and body["status"] == "verified_pass"

    await db_session.refresh(occ)
    assert occ.status == OccurrenceStatus.verified_pass
    n = (
        await db_session.execute(
            select(func.count()).select_from(LedgerEntry).where(LedgerEntry.occurrence_id == occ.id)
        )
    ).scalar_one()
    assert n == 1


async def test_checkin_outside_fence_needs_review(
    client, db_session, household, admin_user, child_user
):
    occ = await _location_occ(db_session, household, child_user)
    await db_session.commit()
    tok = await _token(client, admin_user, child_user)

    r = await client.post(f"/api/v1/checkin/{tok}", json=FAR_AWAY)
    assert r.json()["within"] is False
    await db_session.refresh(occ)
    assert occ.status == OccurrenceStatus.needs_review


async def test_low_accuracy_flag_routes_to_review(
    client, db_session, household, admin_user, child_user
):
    occ = await _location_occ(db_session, household, child_user)
    await db_session.commit()
    tok = await _token(client, admin_user, child_user)

    await client.post(f"/api/v1/checkin/{tok}", json=FUZZY)
    sub = (
        await db_session.execute(select(Submission).where(Submission.occurrence_id == occ.id))
    ).scalar_one()
    assert "LOW_ACCURACY" in sub.flags
    await db_session.refresh(occ)
    assert occ.status == OccurrenceStatus.needs_review


async def test_token_only_touches_location_occurrences(
    client, db_session, household, admin_user, child_user
):
    photo_chore = Chore(
        household_id=household.id,
        title="Kitchen",
        assignment_mode="fixed",
        fixed_assignee_id=child_user.id,
        cadence="daily",
        due_time=time(8, 0),
        start_date=date(2025, 1, 1),
        proof_type="photo",
        verification_mode="manual",
        reward_cents=200,
    )
    db_session.add(photo_chore)
    await db_session.flush()
    db_session.add(
        ChoreOccurrence(
            household_id=household.id,
            chore_id=photo_chore.id,
            assignee_id=child_user.id,
            window_open_at=datetime(2025, 1, 2, tzinfo=UTC),
            due_at=datetime(2025, 1, 2, 16, tzinfo=UTC),
            status=OccurrenceStatus.open,
            reward_cents=200,
        )
    )
    await db_session.commit()
    tok = await _token(client, admin_user, child_user)

    r = await client.post(f"/api/v1/checkin/{tok}", json=AT_SCHOOL)
    assert r.json()["matched"] is False  # the photo occurrence is invisible to the webhook


async def test_rate_limited_to_20_per_hour(client, admin_user, child_user):
    """The per-token cap (spec §6.2). The per-IP cap is lower and would fire first, so it
    is cleared each round — what is under test here is what one leaked token can do."""
    tok = await _token(client, admin_user, child_user)
    for _ in range(20):
        ratelimit._ip_hits.clear()
        await client.post(f"/api/v1/checkin/{tok}", json=AT_SCHOOL)
    ratelimit._ip_hits.clear()
    r = await client.post(f"/api/v1/checkin/{tok}", json=AT_SCHOOL)
    assert r.status_code == 429


async def test_guessing_tokens_is_rate_limited_by_ip(client):
    """Every guess is a different token, so the per-token bucket never fills — without a
    per-IP cap an unauthenticated caller could grind the token space unthrottled, on the
    one path Cloudflare Access is configured to bypass."""
    for i in range(10):
        r = await client.post(f"/api/v1/checkin/guess-{i}", json=AT_SCHOOL)
        assert r.status_code == 404  # unknown token, but not yet throttled
    r = await client.post("/api/v1/checkin/guess-11", json=AT_SCHOOL)
    assert r.status_code == 429


async def test_rotate_invalidates_old_token(client, admin_user, child_user):
    h = await _admin(client)
    old = (await client.get(f"/api/v1/children/{child_user.id}/checkin-token", headers=h)).json()[
        "token"
    ]
    new = (
        await client.post(f"/api/v1/children/{child_user.id}/checkin-token/rotate", headers=h)
    ).json()["token"]
    assert old != new
    assert (await client.post(f"/api/v1/checkin/{old}", json=AT_SCHOOL)).status_code == 404
    assert (await client.post(f"/api/v1/checkin/{new}", json=AT_SCHOOL)).status_code == 200
