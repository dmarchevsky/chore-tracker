"""Phase 8: the scheduler-driven pushes — window opened, due soon, missed (spec §4.5).

VAPID is unset in tests, so ``notify`` records ``skipped`` and pywebpush is never called;
asserting on NotificationLog rows is therefore the whole contract. The submitted → parent
and verdict → kid paths are covered in test_push.py.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from tests.helpers import sign_in

from app.models import Chore, ChoreOccurrence, NotificationLog, OccurrenceStatus
from app.services.scheduler import detect_missed, open_due_windows, send_due_reminders

pytestmark = pytest.mark.asyncio

NOW = datetime(2025, 6, 1, 12, 0, tzinfo=UTC)


def _chore(household, **over) -> Chore:
    base = {
        "household_id": household.id,
        "title": "Kitchen",
        "assignment_mode": "fixed",
        "cadence": "daily",
        "due_time": time(8, 0),
        "window_open_offset_s": -12 * 3600,
        "grace_period_s": 15 * 60,
        "start_date": date(2025, 1, 1),
        "proof_type": "photo",
        "verification_mode": "manual",
        "reward_cents": 200,
    }
    base.update(over)
    return Chore(**base)


@pytest_asyncio.fixture
async def chore(db_session, household, child_user) -> Chore:
    c = _chore(household, fixed_assignee_id=child_user.id)
    db_session.add(c)
    await db_session.commit()
    return c


async def _occ(db_session, household, chore, **over) -> ChoreOccurrence:
    base = {
        "household_id": household.id,
        "chore_id": chore.id,
        "assignee_id": chore.fixed_assignee_id,
        "window_open_at": NOW - timedelta(hours=1),
        "due_at": NOW + timedelta(hours=2),
        "status": OccurrenceStatus.pending,
        "reward_cents": 200,
    }
    base.update(over)
    occ = ChoreOccurrence(**base)
    db_session.add(occ)
    await db_session.commit()
    return occ


async def _kinds(db_session) -> list[str]:
    return [r.kind for r in (await db_session.execute(select(NotificationLog))).scalars()]


async def test_opening_a_window_tells_the_kid_exactly_once(db_session, household, chore):
    await _occ(db_session, household, chore)

    assert await open_due_windows(db_session, now=NOW) == 1
    # The PENDING → OPEN flip is the dedupe: a second sweep has nothing left to claim.
    assert await open_due_windows(db_session, now=NOW) == 0
    await db_session.commit()

    assert await _kinds(db_session) == ["window_open"]


async def test_an_unassigned_occurrence_opens_silently(db_session, household, chore):
    # `anyone` chores carry a NULL assignee — there is nobody to push to (spec §8.1).
    await _occ(db_session, household, chore, assignee_id=None)

    assert await open_due_windows(db_session, now=NOW) == 1
    await db_session.commit()

    assert await _kinds(db_session) == []


async def test_the_reminder_fires_inside_the_lead_and_never_twice(db_session, household, chore):
    await _occ(
        db_session,
        household,
        chore,
        status=OccurrenceStatus.open,
        due_at=NOW + timedelta(minutes=20),
    )

    assert await send_due_reminders(db_session, now=NOW) == 1
    assert await send_due_reminders(db_session, now=NOW + timedelta(minutes=5)) == 0
    await db_session.commit()

    assert await _kinds(db_session) == ["due_soon"]


async def test_no_reminder_before_the_lead_window(db_session, household, chore):
    occ = await _occ(
        db_session, household, chore, status=OccurrenceStatus.open, due_at=NOW + timedelta(hours=2)
    )

    assert await send_due_reminders(db_session, now=NOW) == 0
    await db_session.commit()
    await db_session.refresh(occ)

    assert occ.reminder_sent_at is None
    assert await _kinds(db_session) == []


async def test_a_handed_in_chore_is_not_nudged(db_session, household, chore):
    # Only OPEN rows are nudged: once it is submitted the kid has nothing left to do.
    await _occ(
        db_session,
        household,
        chore,
        status=OccurrenceStatus.submitted,
        due_at=NOW + timedelta(minutes=10),
    )

    assert await send_due_reminders(db_session, now=NOW) == 0
    await db_session.commit()

    assert await _kinds(db_session) == []


async def test_a_miss_reaches_the_kid_and_the_parent(db_session, household, chore, admin_user):
    # TODO(decision): spec §15 Q10 puts misses in the 8:05 digest; this household wants
    # them immediately, so the parent gets one push per miss (see notify_missed).
    await _occ(
        db_session,
        household,
        chore,
        status=OccurrenceStatus.open,
        due_at=NOW - timedelta(hours=1),
        penalty_cents=50,
    )

    assert await detect_missed(db_session, now=NOW) == 1
    await db_session.commit()

    rows = (await db_session.execute(select(NotificationLog))).scalars().all()
    by_kind = {r.kind: r for r in rows}
    assert set(by_kind) == {"missed", "admin.missed"}
    assert by_kind["admin.missed"].user_id == admin_user.id
    assert by_kind["admin.missed"].body == "Alice missed Kitchen."


async def test_an_unassigned_miss_still_reaches_the_parent(
    db_session, household, chore, admin_user
):
    await _occ(
        db_session,
        household,
        chore,
        assignee_id=None,
        status=OccurrenceStatus.open,
        due_at=NOW - timedelta(hours=1),
    )

    assert await detect_missed(db_session, now=NOW) == 1
    await db_session.commit()

    assert await _kinds(db_session) == ["admin.missed"]


async def test_a_redo_carries_the_parents_note_to_the_kid(
    client, db_session, household, chore, admin_user, child_user
):
    occ = await _occ(
        db_session,
        household,
        chore,
        status=OccurrenceStatus.needs_review,
        window_open_at=datetime.now(UTC) - timedelta(hours=6),
        due_at=datetime.now(UTC) - timedelta(hours=1),
    )
    r = await sign_in(client, "parent@example.com")
    resp = await client.post(
        f"/api/v1/occurrences/{occ.id}/decision",
        json={"action": "redo", "reason": "the counter is still sticky"},
        headers={"X-CSRF-Token": r.json()["csrf_token"]},
    )
    assert resp.status_code == 200

    rows = (await db_session.execute(select(NotificationLog))).scalars().all()
    redo = next(x for x in rows if x.kind == "redo")
    assert redo.user_id == child_user.id
    assert redo.body == "the counter is still sticky"


async def test_the_admin_log_carries_what_ops_needs_to_diagnose(
    client, db_session, household, chore, admin_user
):
    # The Ops screen reads this endpoint; `status` and `error` are what tell an operator
    # whether a push failed, was skipped for want of VAPID keys, or had nobody to go to.
    await _occ(
        db_session,
        household,
        chore,
        status=OccurrenceStatus.open,
        due_at=NOW - timedelta(hours=1),
    )
    await detect_missed(db_session, now=NOW)
    await db_session.commit()

    await sign_in(client, "parent@example.com")
    r = await client.get("/api/v1/admin/notifications")

    assert r.status_code == 200
    rows = r.json()
    assert {"kind", "title", "body", "status", "error", "created_at"} <= set(rows[0])
    assert {row["kind"] for row in rows} == {"missed", "admin.missed"}
