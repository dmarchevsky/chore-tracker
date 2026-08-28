"""Append-only audit trail: every admin override, ledger entry, and model call (spec §5)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, uuid_pk


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    # actor: a user id, or "system" for scheduler/worker actions.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    actor_kind: Mapped[str] = mapped_column(String(16), default="user")  # user | system

    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(48), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), default=None, index=True)

    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
