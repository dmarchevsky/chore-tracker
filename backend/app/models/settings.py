"""Runtime-editable household settings (implementation-plan Phase-x admin LLM settings).

One row per household. Every column is nullable: ``NULL`` means "inherit the value from
the environment" (``app.config.Settings``). The admin settings screen writes here so the
vision endpoint / model can be re-pointed without editing ``.env`` and restarting.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, uuid_pk


class HouseholdSettings(TimestampMixin, Base):
    __tablename__ = "household_settings"

    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("households.id", ondelete="CASCADE"), unique=True
    )

    # --- vision LLM connection (overrides LLM_VISION_* env) -----------------
    llm_base_url: Mapped[str | None] = mapped_column(String(255), default=None)
    llm_model: Mapped[str | None] = mapped_column(String(160), default=None)
    llm_api_key: Mapped[str | None] = mapped_column(Text, default=None)
    llm_timeout_s: Mapped[int | None] = mapped_column(Integer, default=None)
    llm_max_retries: Mapped[int | None] = mapped_column(Integer, default=None)

    # --- verification banding defaults (overrides AUTO_*_THRESHOLD env) -----
    auto_pass_threshold: Mapped[float | None] = mapped_column(Numeric(3, 2), default=None)
    auto_fail_threshold: Mapped[float | None] = mapped_column(Numeric(3, 2), default=None)

    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
