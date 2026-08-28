"""Cadence parsing + due-datetime generation (spec §4.1 `cadence`, §8.1, §8.4).

A chore's ``cadence`` string decides *which dates* an occurrence is due; the separate
``due_time`` (local wall-clock ``HH:MM``) decides the time on each of those dates. All
wall-clock math happens in the household timezone and the result is returned as
timezone-aware UTC datetimes — "before 8am" means 8am local, across DST boundaries.

Supported grammar (case-insensitive, whitespace-insensitive):

    daily
    weekdays                     Mon-Fri
    weekends                     Sat-Sun
    weekly(on=[SAT])             one or more of MON TUE WED THU FRI SAT SUN
    weekly(on=[MON,WED,FRI])
    monthly(day=15)              1..31; clamped to the last day of shorter months
    custom_rule                  not implemented in v1 (see TODO(decision))
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

__all__ = ["CadenceError", "cadence_dates", "due_datetimes"]

_WEEKDAY_TOKENS = {
    "MON": 0,
    "TUE": 1,
    "WED": 2,
    "THU": 3,
    "FRI": 4,
    "SAT": 5,
    "SUN": 6,
}

_WEEKLY_RE = re.compile(r"^weekly\(on=\[([A-Za-z,]+)\]\)$")
_MONTHLY_RE = re.compile(r"^monthly\(day=(\d{1,2})\)$")

_UTC = ZoneInfo("UTC")


class CadenceError(ValueError):
    """Raised for an unparseable or unsupported cadence string."""


def _iter_days(start: date, end: date) -> Iterator[date]:
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _parse_weekdays(raw: str) -> set[int]:
    days: set[int] = set()
    for tok in (t.strip().upper() for t in raw.split(",")):
        if tok not in _WEEKDAY_TOKENS:
            raise CadenceError(f"unknown weekday token {tok!r}")
        days.add(_WEEKDAY_TOKENS[tok])
    if not days:
        raise CadenceError("weekly(on=[...]) needs at least one weekday")
    return days


def _monthly_dates(day_n: int, start: date, end: date) -> list[date]:
    out: list[date] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        last = calendar.monthrange(year, month)[1]
        d = date(year, month, min(day_n, last))
        if start <= d <= end:
            out.append(d)
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return out


def cadence_dates(cadence: str, start: date, end: date) -> list[date]:
    """Return every date in ``[start, end]`` (inclusive) on which the cadence fires."""
    if end < start:
        return []

    norm = re.sub(r"\s+", "", cadence.strip()).lower()

    if norm == "daily":
        return list(_iter_days(start, end))
    if norm == "weekdays":
        return [d for d in _iter_days(start, end) if d.weekday() < 5]
    if norm == "weekends":
        return [d for d in _iter_days(start, end) if d.weekday() >= 5]

    m = _WEEKLY_RE.match(norm)
    if m:
        wanted = _parse_weekdays(m.group(1))
        return [d for d in _iter_days(start, end) if d.weekday() in wanted]

    m = _MONTHLY_RE.match(norm)
    if m:
        day_n = int(m.group(1))
        if not 1 <= day_n <= 31:
            raise CadenceError("monthly(day=N) needs 1 <= N <= 31")
        return _monthly_dates(day_n, start, end)

    if norm == "custom_rule":
        # TODO(decision): spec §4.1 lists custom_rule but gives no grammar. Until one is
        # defined, a chore may not use it.
        raise CadenceError("custom_rule is not implemented in v1")

    raise CadenceError(f"unparseable cadence {cadence!r}")


def due_datetimes(
    cadence: str,
    start: date,
    end: date,
    due_time: time,
    tz: ZoneInfo,
) -> list[datetime]:
    """Cadence dates combined with ``due_time`` in ``tz``, returned as UTC datetimes."""
    result: list[datetime] = []
    for d in cadence_dates(cadence, start, end):
        local = datetime.combine(d, due_time, tzinfo=tz)
        result.append(local.astimezone(_UTC))
    return result
