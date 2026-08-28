"""Deterministic assignee rotation (spec §8.2).

No "whose turn is it" state to drift — the assignee for any due date is a pure function
of the ordered ``assignee_ids``, the ``anchor_date``, and the rotation period.

    weeks_since_anchor = (iso_week_start(due) - iso_week_start(anchor)).days // 7
    idx = (weeks_since_anchor // (2 if biweekly else 1)) % len(assignee_ids)   # weekly/biweekly
    idx = (due - anchor).days % len(assignee_ids)                              # daily
"""

from __future__ import annotations

import enum
from collections.abc import Sequence
from datetime import date, timedelta

__all__ = ["RotationError", "RotationPeriod", "iso_week_start", "rotation_pick", "rotation_preview"]


class RotationPeriod(enum.StrEnum):
    daily = "daily"
    weekly = "weekly"
    biweekly = "biweekly"


class RotationError(ValueError):
    """Raised for a malformed rotation configuration."""


def iso_week_start(d: date) -> date:
    """Monday of ``d``'s week."""
    return d - timedelta(days=d.weekday())


def _units_since_anchor(anchor: date, due: date, period: RotationPeriod) -> int:
    if period is RotationPeriod.daily:
        return (due - anchor).days
    weeks = (iso_week_start(due) - iso_week_start(anchor)).days // 7
    if period is RotationPeriod.biweekly:
        return weeks // 2
    return weeks


def rotation_pick[T](
    assignee_ids: Sequence[T],
    anchor_date: date,
    due_date: date,
    period: RotationPeriod | str,
) -> T:
    """Return the assignee for ``due_date``.

    ``idx`` is taken modulo ``len(assignee_ids)`` and floored at 0, so dates before the
    anchor still resolve to a stable, in-range assignee (Python's ``%`` already wraps
    negatives upward, which keeps the sequence continuous across the anchor).
    """
    if not assignee_ids:
        raise RotationError("assignee_ids is empty")
    period = RotationPeriod(period)
    idx = _units_since_anchor(anchor_date, due_date, period) % len(assignee_ids)
    return assignee_ids[idx]


def rotation_preview[T](
    assignee_ids: Sequence[T],
    anchor_date: date,
    start_date: date,
    period: RotationPeriod | str,
    count: int,
    step_days: int = 7,
) -> list[T]:
    """``count`` successive picks starting at ``start_date``, one every ``step_days``.

    Handy for the admin "next 4 weeks: Alice, Alice, Bea, Bea" preview (spec §8.2).
    """
    if count < 0:
        raise RotationError("count must be >= 0")
    return [
        rotation_pick(assignee_ids, anchor_date, start_date + timedelta(days=i * step_days), period)
        for i in range(count)
    ]
