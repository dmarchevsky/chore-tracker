"""Kid-filed disputes — "this isn't right" (spec §4.2, §6.3 rule 1).

The model and the scheduler both get things wrong, so a kid must be able to say so and
have a parent actually see it. A dispute never changes the occurrence's status on its own
— it is a message with a state, resolved by a parent who then decides the occurrence
through the normal review path.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, uuid_pk


class DisputeStatus(enum.StrEnum):
    open = "open"
    resolved = "resolved"


class Dispute(TimestampMixin, Base):
    __tablename__ = "disputes"

    id: Mapped[uuid.UUID] = uuid_pk()
    occurrence_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("chore_occurrences.id", ondelete="CASCADE"), index=True
    )
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    message: Mapped[str] = mapped_column(Text)
    # The occurrence status when it was filed — what the kid was actually objecting to.
    status_at_filing: Mapped[str | None] = mapped_column(String(24), default=None)

    status: Mapped[DisputeStatus] = mapped_column(
        String(16), default=DisputeStatus.open, index=True
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, default=None)
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
