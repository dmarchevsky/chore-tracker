"""The single household. Tenancy is hardcoded to one row in v1 (spec §1 non-goals)."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, uuid_pk


class Household(TimestampMixin, Base):
    __tablename__ = "households"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(default="Home")
    timezone: Mapped[str] = mapped_column(default="America/Los_Angeles")
    currency: Mapped[str] = mapped_column(default="USD")
