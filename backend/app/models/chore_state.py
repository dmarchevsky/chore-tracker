"""Flip history for a standing chore (spec §4.7).

Why a table rather than only ``audit_log``: the audit log genuinely records who and when,
but it is the *admin* forensic trail — generic before/after JSONB, never exposed to a
child. A kid needs to see what is currently in force and since when, so this is the
kid-visible system of record. Both are written on every flip.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, uuid_pk


class ChoreStateEvent(TimestampMixin, Base):
    __tablename__ = "chore_state_events"
    __table_args__ = (Index("ix_chore_state_chore_created", "chore_id", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    chore_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("chores.id", ondelete="CASCADE"), index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    state: Mapped[bool] = mapped_column(Boolean)  # True = flipped on
    tier_id: Mapped[int | None] = mapped_column(Integer, default=None)
    # Snapshot of the tier as it read at flip time, so renaming the condition later doesn't
    # rewrite what the kid was told (same rule as the occurrence tier snapshot, spec §3).
    tier: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)
