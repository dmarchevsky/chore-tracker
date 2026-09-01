"""Phase 2: cadence parsing + DST-safe due-datetime generation (spec §8.1, §8.4)."""

from __future__ import annotations

from datetime import date, time
from zoneinfo import ZoneInfo

import pytest

from app.services.cadence import CadenceError, cadence_dates, due_datetimes, once_date

LA = ZoneInfo("America/Los_Angeles")
UTC = ZoneInfo("UTC")


def test_daily_is_every_day():
    got = cadence_dates("daily", date(2025, 1, 1), date(2025, 1, 5))
    assert got == [date(2025, 1, d) for d in range(1, 6)]


def test_weekdays_and_weekends_partition_the_week():
    span = (date(2025, 6, 2), date(2025, 6, 8))  # Mon..Sun
    weekdays = cadence_dates("weekdays", *span)
    weekends = cadence_dates("weekends", *span)
    assert [d.weekday() for d in weekdays] == [0, 1, 2, 3, 4]
    assert [d.weekday() for d in weekends] == [5, 6]
    assert sorted(weekdays + weekends) == cadence_dates("daily", *span)


def test_weekly_single_day():
    got = cadence_dates("weekly(on=[SAT])", date(2025, 3, 1), date(2025, 3, 31))
    assert got == [date(2025, 3, d) for d in (1, 8, 15, 22, 29)]
    assert all(d.weekday() == 5 for d in got)


def test_weekly_multi_day_is_whitespace_and_case_insensitive():
    a = cadence_dates("weekly(on=[MON,WED,FRI])", date(2025, 3, 3), date(2025, 3, 9))
    b = cadence_dates("weekly( on=[ mon , wed , fri ] )", date(2025, 3, 3), date(2025, 3, 9))
    assert a == b == [date(2025, 3, 3), date(2025, 3, 5), date(2025, 3, 7)]


def test_monthly_clamps_short_months():
    # monthly(day=31) across Jan..Apr → last day of each month.
    got = cadence_dates("monthly(day=31)", date(2025, 1, 1), date(2025, 4, 30))
    assert got == [date(2025, 1, 31), date(2025, 2, 28), date(2025, 3, 31), date(2025, 4, 30)]


def test_monthly_leap_year_february():
    got = cadence_dates("monthly(day=30)", date(2024, 2, 1), date(2024, 2, 29))
    assert got == [date(2024, 2, 29)]


def test_monthly_respects_range_bounds():
    got = cadence_dates("monthly(day=15)", date(2025, 1, 20), date(2025, 3, 10))
    assert got == [date(2025, 2, 15)]


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "hourly",
        "weekly",
        "weekly(on=[])",
        "weekly(on=[FUNDAY])",
        "monthly(day=0)",
        "monthly(day=32)",
        "custom_rule",
    ],
)
def test_unparseable_cadence_raises(bad):
    with pytest.raises(CadenceError):
        cadence_dates(bad, date(2025, 1, 1), date(2025, 1, 31))


def test_empty_when_end_before_start():
    assert cadence_dates("daily", date(2025, 2, 1), date(2025, 1, 1)) == []


def test_due_time_is_local_wallclock_across_spring_forward():
    # US DST begins 2025-03-09 02:00 (PST -> PDT).  08:00 local must stay 08:00 local.
    got = due_datetimes("daily", date(2025, 3, 8), date(2025, 3, 10), time(8, 0), LA)
    assert all(dt.tzinfo == UTC for dt in got)
    local = [dt.astimezone(LA) for dt in got]
    assert [d.hour for d in local] == [8, 8, 8]
    assert {d.minute for d in local} == {0}
    # UTC offset actually shifts: 16:00Z before, 15:00Z on/after the transition.
    assert [dt.hour for dt in got] == [16, 15, 15]


def test_due_time_is_local_wallclock_across_fall_back():
    # US DST ends 2025-11-02 02:00 (PDT -> PST).
    got = due_datetimes("daily", date(2025, 11, 1), date(2025, 11, 3), time(8, 0), LA)
    local = [dt.astimezone(LA) for dt in got]
    assert [d.hour for d in local] == [8, 8, 8]
    assert [dt.hour for dt in got] == [15, 16, 16]


def test_due_datetimes_empty_for_no_matches():
    assert (
        due_datetimes("weekly(on=[SUN])", date(2025, 3, 3), date(2025, 3, 7), time(8, 0), LA) == []
    )


def test_once_fires_only_on_its_date():
    assert cadence_dates("once(2026-09-14)", date(2026, 9, 1), date(2026, 9, 30)) == [
        date(2026, 9, 14)
    ]
    # inclusive at both ends of a single-day window
    assert cadence_dates("once(2026-09-14)", date(2026, 9, 14), date(2026, 9, 14)) == [
        date(2026, 9, 14)
    ]


def test_once_outside_the_window_returns_nothing():
    """The scheduler clamps its window to [max(start_date, today), horizon]. Once the date
    has passed, the window never contains it again, so the chore stops generating."""
    assert cadence_dates("once(2026-09-14)", date(2026, 10, 1), date(2026, 10, 30)) == []
    assert cadence_dates("once(2026-09-14)", date(2026, 8, 1), date(2026, 8, 30)) == []


def test_once_rejects_a_date_that_does_not_exist():
    with pytest.raises(CadenceError):
        cadence_dates("once(2026-02-30)", date(2026, 1, 1), date(2026, 12, 31))


def test_once_is_whitespace_and_case_tolerant():
    assert cadence_dates("  ONCE( 2026-09-14 )  ", date(2026, 9, 1), date(2026, 9, 30)) == [
        date(2026, 9, 14)
    ]


def test_once_date_extracts_the_date_only_for_a_one_off():
    assert once_date("once(2026-09-14)") == date(2026, 9, 14)
    assert once_date("ONCE( 2026-09-14 )") == date(2026, 9, 14)
    assert once_date("daily") is None
    assert once_date("weekly(on=[SAT])") is None
    assert once_date("once(2026-02-30)") is None  # malformed: not a one-off we can act on


def test_once_carries_the_due_time_like_any_other_cadence():
    got = due_datetimes("once(2026-09-14)", date(2026, 9, 1), date(2026, 9, 30), time(8, 0), LA)
    assert len(got) == 1
    assert got[0].astimezone(LA).hour == 8
