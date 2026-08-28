"""Per-kid check-in webhook tokens (spec §6.2).

High-entropy, revocable, rate-limited. A token can only transition a ``location``
occurrence that is currently ``OPEN`` — it can never approve a photo chore or write an
arbitrary ledger entry. Assume the token leaks eventually.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, uuid_pk


class CheckinToken(TimestampMixin, Base):
    __tablename__ = "checkin_tokens"

    id: Mapped[uuid.UUID] = uuid_pk()
    child_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    @property
    def active(self) -> bool:
        return self.revoked_at is None
