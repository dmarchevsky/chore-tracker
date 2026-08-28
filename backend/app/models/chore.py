"""Chore *definition* (spec §4.1).

A Chore is a rule. The scheduler materialises it into concrete
:class:`~app.models.occurrence.ChoreOccurrence` rows; all proof, verification, money and
history hang off the occurrence, never the definition (spec §3).
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, time
from typing import Any

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text, Time
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, uuid_pk


class AssignmentMode(enum.StrEnum):
    fixed = "fixed"
    rotating = "rotating"
    anyone = "anyone"
    all = "all"


class ProofType(enum.StrEnum):
    photo = "photo"
    location = "location"
    photo_location = "photo+location"
    acknowledgement = "acknowledgement"
    none = "none"


class VerificationMode(enum.StrEnum):
    llm_auto = "llm_auto"
    llm_assist = "llm_assist"
    manual = "manual"
    auto_accept = "auto_accept"


class Chore(TimestampMixin, Base):
    __tablename__ = "chores"

    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("households.id", ondelete="CASCADE"), index=True
    )

    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")

    # --- Assignment ------------------------------------------------------
    assignment_mode: Mapped[AssignmentMode] = mapped_column(String(16))
    fixed_assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    # Ordered — this is what makes "every other week" deterministic (spec §8.2).
    assignee_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(PgUUID(as_uuid=True)), default=list)
    rotation_period: Mapped[str | None] = mapped_column(String(16), default=None)
    rotation_anchor_date: Mapped[date | None] = mapped_column(Date, default=None)

    # --- Schedule ------------------------------------------------------
    cadence: Mapped[str] = mapped_column(String(120))
    due_time: Mapped[time] = mapped_column(Time)  # local wall-clock; TZ is household-level
    window_open_offset_s: Mapped[int] = mapped_column(Integer, default=-12 * 3600)
    grace_period_s: Mapped[int] = mapped_column(Integer, default=15 * 60)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, default=None)

    # --- Proof ------------------------------------------------------
    proof_type: Mapped[ProofType] = mapped_column(String(24))
    photo_count: Mapped[int] = mapped_column(Integer, default=1)
    photo_prompts: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    allow_gallery_upload: Mapped[bool] = mapped_column(Boolean, default=False)
    prompt_token_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    geofence: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)

    # --- Verification ------------------------------------------------------
    verification_mode: Mapped[VerificationMode] = mapped_column(String(16))
    verification_rule: Mapped[str | None] = mapped_column(Text, default=None)
    verification_checklist: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, default=None)
    auto_pass_threshold: Mapped[float] = mapped_column(Numeric(3, 2), default=0.85)
    auto_fail_threshold: Mapped[float] = mapped_column(Numeric(3, 2), default=0.35)

    # --- Money (integer cents, spec §9) --------------------------------
    reward_cents: Mapped[int] = mapped_column(Integer, default=0)
    penalty_cents: Mapped[int] = mapped_column(Integer, default=0)
    late_multiplier: Mapped[float] = mapped_column(Numeric(4, 2), default=1.0)

    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
