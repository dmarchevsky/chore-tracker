"""Phase 2: deterministic rotation math (spec §8.2)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from app.services.rotation import (
    RotationError,
    RotationPeriod,
    iso_week_start,
    rotation_pick,
    rotation_preview,
)

ALICE, BEA, CID = "alice", "bea", "cid"
ANCHOR = date(2025, 1, 6)  # a Monday


def test_iso_week_start_is_monday():
    assert iso_week_start(date(2025, 1, 8)) == date(2025, 1, 6)
    assert iso_week_start(date(2025, 1, 6)) == date(2025, 1, 6)
    assert iso_week_start(date(2025, 1, 12)) == date(2025, 1, 6)  # Sunday still same week


def test_biweekly_preview_is_alice_alice_bea_bea():
    got = rotation_preview([ALICE, BEA], ANCHOR, ANCHOR, RotationPeriod.biweekly, count=4)
    assert got == [ALICE, ALICE, BEA, BEA]


def test_weekly_preview_alternates():
    got = rotation_preview([ALICE, BEA], ANCHOR, ANCHOR, "weekly", count=4)
    assert got == [ALICE, BEA, ALICE, BEA]


def test_daily_rotation_cycles_every_day():
    got = rotation_preview([ALICE, BEA, CID], ANCHOR, ANCHOR, "daily", count=5, step_days=1)
    assert got == [ALICE, BEA, CID, ALICE, BEA]


def test_same_week_days_share_an_assignee_for_weekly():
    mon = date(2025, 2, 3)
    sun = date(2025, 2, 9)
    picks = {
        rotation_pick([ALICE, BEA], ANCHOR, mon + timedelta(days=i), "weekly") for i in range(7)
    }
    assert picks == {rotation_pick([ALICE, BEA], ANCHOR, mon, "weekly")}
    assert mon.weekday() == 0 and sun.weekday() == 6


def test_sequence_is_continuous_across_the_anchor():
    # weeks -2, -1, 0, 1 with a 2-person weekly rotation -> a, b, a, b
    picks = [
        rotation_pick([ALICE, BEA], ANCHOR, ANCHOR + timedelta(weeks=w), "weekly")
        for w in (-2, -1, 0, 1)
    ]
    assert picks == [ALICE, BEA, ALICE, BEA]


def test_empty_assignees_raises():
    with pytest.raises(RotationError):
        rotation_pick([], ANCHOR, ANCHOR, "weekly")


def test_bad_period_raises():
    with pytest.raises(ValueError):
        rotation_pick([ALICE], ANCHOR, ANCHOR, "fortnightly")
