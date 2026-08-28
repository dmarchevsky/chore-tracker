"""Materialised chore occurrence (spec §3).

One concrete instance per due datetime with a resolved assignee. The scheduler upserts
these on the key ``(chore_id, due_at, assignee_id)`` so generation is idempotent (spec §8.1).
Money terms are snapshotted here at generation time so later edits to the Chore never
rewrite history (spec §3, §4.1).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, uuid_pk


class OccurrenceStatus(enum.StrEnum):
    pending = "pending"
    open = "open"
    submitted = "submitted"
    verified_pass = "verified_pass"
    verified_fail = "verified_fail"
    needs_review = "needs_review"
    missed = "missed"
    approved = "approved"  # terminal, admin
    rejected = "rejected"  # terminal, admin
    excused = "excused"  # terminal, admin, no money impact


# States that still accept a new submission (spec §3).
SUBMITTABLE = {
    OccurrenceStatus.open,
    OccurrenceStatus.needs_review,
    OccurrenceStatus.verified_fail,
}
# Terminal admin decisions.
TERMINAL = {
    OccurrenceStatus.approved,
    OccurrenceStatus.rejected,
    OccurrenceStatus.excused,
}


class ChoreOccurrence(TimestampMixin, Base):
    __tablename__ = "chore_occurrences"
    __table_args__ = (
        UniqueConstraint("chore_id", "due_at", "assignee_id", name="uq_occurrence_slot"),
        # `anyone` occurrences carry a NULL assignee; keep exactly one per (chore, due_at).
        Index(
            "uq_occurrence_unassigned_slot",
            "chore_id",
            "due_at",
            unique=True,
            postgresql_where=text("assignee_id IS NULL"),
        ),
        Index("ix_occurrence_status_due", "status", "due_at"),
        Index("ix_occurrence_assignee_due", "assignee_id", "due_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    chore_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("chores.id", ondelete="CASCADE"), index=True
    )
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    window_open_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[OccurrenceStatus] = mapped_column(String(16), default=OccurrenceStatus.pending)
    was_late: Mapped[bool] = mapped_column(Boolean, default=False)
    settlement_locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    # Money terms snapshotted from the Chore at generation (spec §3).
    reward_cents: Mapped[int] = mapped_column(Integer, default=0)
    penalty_cents: Mapped[int] = mapped_column(Integer, default=0)
    late_multiplier: Mapped[float] = mapped_column(Numeric(4, 2), default=1.0)
