"""Users: two roles only — admin (parent) and child (spec §2)."""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, uuid_pk


class UserRole(enum.StrEnum):
    admin = "admin"
    child = "child"


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("household_id", "username", name="uq_user_username"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    username: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[UserRole] = mapped_column(String(16))
    password_hash: Mapped[str] = mapped_column(String(255))

    # TOTP is required for admins (spec §12.1), unused for children.
    totp_secret: Mapped[str | None] = mapped_column(String(64), default=None)
    totp_enrolled: Mapped[bool] = mapped_column(Boolean, default=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.admin
