"""Verification records — llm or manual (spec §3, §7).

Every model call and every admin decision is stored with its full context so a verdict can
be defended later (spec §6.3 rule 5). The model is an assistant, not a judge.
"""

from __future__ import annotations

import enum
import uuid
from typing import Any

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, uuid_pk


class VerificationKind(enum.StrEnum):
    llm = "llm"
    manual = "manual"


class Verdict(enum.StrEnum):
    pass_ = "pass"
    fail = "fail"
    needs_review = "needs_review"
    error = "error"  # infra failure — fail-open to review, never VERIFIED_FAIL (spec §6.3)


class Verification(TimestampMixin, Base):
    __tablename__ = "verifications"

    id: Mapped[uuid.UUID] = uuid_pk()
    occurrence_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("chore_occurrences.id", ondelete="CASCADE"), index=True
    )
    submission_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("submissions.id", ondelete="SET NULL"), default=None
    )

    kind: Mapped[VerificationKind] = mapped_column(String(8))
    verdict: Mapped[Verdict] = mapped_column(String(16))
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), default=None)
    reasoning: Mapped[str | None] = mapped_column(Text, default=None)
    child_message: Mapped[str | None] = mapped_column(Text, default=None)

    checks: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, default=None)
    image_quality_issue: Mapped[str | None] = mapped_column(String(24), default=None)

    # Full model I/O (spec §6.3 rule 5) — populated by the Phase 4 worker.
    model_name: Mapped[str | None] = mapped_column(String(120), default=None)
    raw_request: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)

    created_by: Mapped[str] = mapped_column(String(8), default="system")  # system | user
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
