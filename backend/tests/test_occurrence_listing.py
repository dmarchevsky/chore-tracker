"""Listing filters + paging behind the parent's History view (spec §4.2, §10)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest
import pytest_asyncio
from tests.helpers import sign_in

from app.models import Chore, ChoreOccurrence, OccurrenceStatus

pytestmark = pytest.mark.asyncio

BASE = datetime(2025, 3, 1, 16, tzinfo=UTC)


async def _chore(db, household, child, title="Kitchen") -> Chore:
    c = Chore(
        household_id=household.id,
        title=title,
        assignment_mode="fixed",
        fixed_assignee_id=child.id,
        cadence="daily",
        due_time=time(8, 0),
        start_date=date(2025, 1, 1),
        proof_type="photo",
        verification_mode="manual",
        reward_cents=200,
    )
    db.add(c)
    await db.flush()
    return c


@pytest_asyncio.fixture
async def seeded(db_session, household, child_user):
    """12 occurrences: alternating approved/rejected, one day apart."""
    chore = await _chore(db_session, household, child_user)
    other = await _chore(db_session, household, child_user, title="Dog")
    made = []
    for i in range(12):
        occ = ChoreOccurrence(
            household_id=household.id,
            chore_id=chore.id if i % 3 else other.id,
            assignee_id=child_user.id,
            window_open_at=BASE + timedelta(days=i),
            due_at=BASE + timedelta(days=i, hours=2),
            status=OccurrenceStatus.approved if i % 2 else OccurrenceStatus.rejected,
            reward_cents=200,
        )
        db_session.add(occ)
        made.append(occ)
    await db_session.commit()
    return made


async def _admin_login(client):
    r = await sign_in(client, "parent@example.com")
    return {"X-CSRF-Token": r.json()["csrf_token"]}


async def test_offset_pages_without_overlap_and_reports_the_total(client, seeded, admin_user):
    ah = await _admin_login(client)
    first = await client.get("/api/v1/occurrences?limit=5&order=desc", headers=ah)
    second = await client.get("/api/v1/occurrences?limit=5&offset=5&order=desc", headers=ah)

    assert first.headers["X-Total-Count"] == "12"
    ids1 = [o["id"] for o in first.json()]
    ids2 = [o["id"] for o in second.json()]
    assert len(ids1) == len(ids2) == 5
    assert not set(ids1) & set(ids2)


async def test_repeated_status_filters_are_ored(client, seeded, admin_user):
    ah = await _admin_login(client)
    both = await client.get("/api/v1/occurrences?status=approved&status=rejected", headers=ah)
    one = await client.get("/api/v1/occurrences?status=approved", headers=ah)

    assert both.headers["X-Total-Count"] == "12"
    assert one.headers["X-Total-Count"] == "6"
    assert {o["status"] for o in one.json()} == {"approved"}


async def test_chore_filter_narrows_the_list(client, seeded, admin_user):
    ah = await _admin_login(client)
    chore_id = seeded[0].chore_id  # the "Dog" chore, every third occurrence
    r = await client.get(f"/api/v1/occurrences?chore={chore_id}", headers=ah)
    assert {o["chore_id"] for o in r.json()} == {str(chore_id)}
    assert r.headers["X-Total-Count"] == "4"


async def test_a_child_is_still_scoped_to_their_own_occurrences(
    client, db_session, seeded, household, child_user
):
    from app.models import User
    from app.models.user import UserRole

    bob = User(
        household_id=household.id,
        username="bob",
        display_name="Bob",
        role=UserRole.child,
        email="bob@example.com",
    )
    db_session.add(bob)
    await db_session.commit()

    r = await sign_in(client, "bob@example.com")
    headers = {"X-CSRF-Token": r.json()["csrf_token"]}
    # ...even when they ask for someone else's.
    listed = await client.get(f"/api/v1/occurrences?child={child_user.id}", headers=headers)
    assert listed.json() == []
    assert listed.headers["X-Total-Count"] == "0"
