"""Phase 2: chore/occurrence schema validation + table constraints (spec §3, §4.1, §8.1)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.models import Chore, ChoreOccurrence, OccurrenceStatus
from app.models.occurrence import SUBMITTABLE, TERMINAL
from app.schemas.chore import ChoreCreate

_A, _B = uuid.uuid4(), uuid.uuid4()


def _valid_rotating(**over) -> dict:
    base = {
        "title": "Kitchen",
        "assignment_mode": "rotating",
        "assignee_ids": [_A, _B],
        "rotation_period": "biweekly",
        "rotation_anchor_date": date(2025, 1, 6),
        "cadence": "daily",
        "due_time": time(8, 0),
        "start_date": date(2025, 1, 1),
        "proof_type": "photo",
        "photo_count": 1,
        "verification_mode": "llm_auto",
        "reward_cents": 200,
    }
    base.update(over)
    return base


def test_valid_rotating_chore_parses():
    c = ChoreCreate(**_valid_rotating())
    assert c.assignment_mode == "rotating"
    assert c.auto_pass_threshold == 0.85


@pytest.mark.parametrize(
    "override, msg",
    [
        (
            {"assignment_mode": "fixed", "assignee_ids": [], "fixed_assignee_id": None},
            "fixed_assignee_id",
        ),
        ({"assignee_ids": [_A]}, ">= 2 assignee_ids"),
        ({"rotation_period": None}, "rotation_period"),
        ({"cadence": "hourly"}, "invalid cadence"),
        ({"end_date": date(2024, 1, 1)}, "end_date"),
        ({"auto_pass_threshold": 0.2, "auto_fail_threshold": 0.9}, "auto_fail_threshold"),
        ({"proof_type": "location", "geofence": None}, "geofence"),
    ],
)
def test_invalid_chore_rejected(override, msg):
    with pytest.raises(ValidationError) as ei:
        ChoreCreate(**_valid_rotating(**override))
    assert msg in str(ei.value)


def test_location_chore_with_geofence_ok():
    c = ChoreCreate(
        **_valid_rotating(
            proof_type="location",
            photo_count=0,
            geofence={"lat": 37.7, "lon": -122.4, "radius_m": 120, "arrive_before": "08:10"},
        )
    )
    assert c.geofence.radius_m == 120


def test_state_sets_are_expected():
    assert OccurrenceStatus.open in SUBMITTABLE
    assert OccurrenceStatus.missed not in SUBMITTABLE
    assert TERMINAL == {
        OccurrenceStatus.approved,
        OccurrenceStatus.rejected,
        OccurrenceStatus.excused,
    }


async def _mk_chore(db, household) -> Chore:
    chore = Chore(
        household_id=household.id,
        title="Kitchen",
        assignment_mode="fixed",
        cadence="daily",
        due_time=time(8, 0),
        start_date=date(2025, 1, 1),
        proof_type="photo",
        verification_mode="manual",
        reward_cents=200,
    )
    db.add(chore)
    await db.commit()
    return chore


async def test_occurrence_slot_uniqueness(db_session, household, child_user):
    chore = await _mk_chore(db_session, household)
    due = datetime(2025, 1, 2, 16, 0, tzinfo=UTC)

    def _occ(assignee):
        return ChoreOccurrence(
            household_id=household.id,
            chore_id=chore.id,
            assignee_id=assignee,
            window_open_at=due,
            due_at=due,
            status=OccurrenceStatus.open,
        )

    db_session.add(_occ(child_user.id))
    await db_session.commit()

    db_session.add(_occ(child_user.id))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_unassigned_slot_uniqueness(db_session, household):
    chore = await _mk_chore(db_session, household)
    due = datetime(2025, 1, 3, 16, 0, tzinfo=UTC)

    def _occ():
        return ChoreOccurrence(
            household_id=household.id,
            chore_id=chore.id,
            assignee_id=None,
            window_open_at=due,
            due_at=due,
            status=OccurrenceStatus.open,
        )

    db_session.add(_occ())
    await db_session.commit()

    db_session.add(_occ())
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
