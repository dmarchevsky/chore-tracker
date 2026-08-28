"""Postgres-backed verification job queue (spec §7.1, §13.1 — no Redis).

Workers claim rows with ``SELECT ... FOR UPDATE SKIP LOCKED``. A row stuck in ``running``
past a timeout is requeued on startup (spec §8.3).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, uuid_pk


class JobState(enum.StrEnum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


class VerificationJob(TimestampMixin, Base):
    __tablename__ = "verification_jobs"

    id: Mapped[uuid.UUID] = uuid_pk()
    occurrence_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("chore_occurrences.id", ondelete="CASCADE"), index=True
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("submissions.id", ondelete="CASCADE")
    )
    state: Mapped[JobState] = mapped_column(String(12), default=JobState.queued, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
