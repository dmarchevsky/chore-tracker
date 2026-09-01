"""Materialised chore occurrence (spec §3).

One concrete instance per due datetime with a resolved assignee. The scheduler upserts
these on the key ``(chore_id, due_at, assignee_id)`` so generation is idempotent (spec §8.1).
Money terms are snapshotted here at generation time so later edits to the Chore never
rewrite history (spec §3, §4.1).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timedelta
from typing import Any

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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.config import get_settings
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
    # When the scheduler settled a MISSED occurrence — i.e. posted the penalty, or decided
    # there was none to post. The ledger's (occurrence_id, kind) index already makes the
    # debit exactly-once; this is what keeps the settlement scan off rows it is done with,
    # and what tells the kid the money has actually moved.
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # Money terms snapshotted from the Chore at generation (spec §3).
    reward_cents: Mapped[int] = mapped_column(Integer, default=0)
    penalty_cents: Mapped[int] = mapped_column(Integer, default=0)
    # TODO(decision): was_late is never set to True anywhere, so late_multiplier and
    # ledger._late_adjusted are inert (spec §15 Q16). Setting it belongs in ingest_submission
    # (now > due_at); until then the admin form deliberately does not offer the multiplier.
    late_multiplier: Mapped[float] = mapped_column(Numeric(4, 2), default=1.0)

    # Snapshot of the chore's tier list at generation time, for the same reason the money
    # terms above are snapshotted (spec §3): editing "+$100" down to "+$50" must not
    # re-price a report card the kid already handed in. NULL on rows generated before
    # tiers existed — the decision path falls back to the chore's current list.
    outcome_tiers: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, default=None)
    # The tier the admin picked, and a snapshot of it as it read at decision time.
    outcome_tier_id: Mapped[int | None] = mapped_column(Integer, default=None)
    outcome_tier: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)

    # Set when the LLM path fails open to NEEDS_REVIEW (spec §6.3 rule 3).
    verification_error: Mapped[str | None] = mapped_column(String(200), default=None)

    @property
    def appeal_closes_at(self) -> datetime:
        """After this, a kid can no longer contest the occurrence themselves (spec §4.2).

        Not a column: the window is a household-wide setting, so a row must never freeze an
        old value of it. A parent still has excuse/approve for anything older.
        """
        return self.due_at + timedelta(seconds=get_settings().appeal_window_s)
