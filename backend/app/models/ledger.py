"""Append-only money ledger (spec §9).

Integer cents, no floats, no UPDATEs. A correction is a reversing ``adjustment`` entry with
``reversed_by_entry_id`` set on the original. Balance = SUM(amount_cents) per child. A
partial unique index on ``(occurrence_id, kind)`` for earning/penalty makes payment
exactly-once — a double-clicked approve cannot double-pay.
"""

from __future__ import annotations

import enum
import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, uuid_pk


class LedgerKind(enum.StrEnum):
    earning = "earning"
    penalty = "penalty"
    bonus = "bonus"
    adjustment = "adjustment"
    payout = "payout"


EARN_KINDS = (LedgerKind.earning, LedgerKind.penalty)


class LedgerEntry(TimestampMixin, Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        Index(
            "uq_ledger_occurrence_earn_kind",
            "occurrence_id",
            "kind",
            unique=True,
            postgresql_where=text("kind IN ('earning','penalty')"),
        ),
        Index("ix_ledger_child", "child_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    child_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    occurrence_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("chore_occurrences.id", ondelete="SET NULL"),
        default=None,
        index=True,
    )

    kind: Mapped[LedgerKind] = mapped_column(String(16))
    amount_cents: Mapped[int] = mapped_column(BigInteger)  # signed
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    reason: Mapped[str] = mapped_column(Text, default="")

    created_by: Mapped[str] = mapped_column(String(8), default="system")  # user | system
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    reversed_by_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("ledger_entries.id", ondelete="SET NULL"), default=None
    )
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
