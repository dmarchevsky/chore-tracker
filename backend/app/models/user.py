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
    __table_args__ = (
        UniqueConstraint("household_id", "username", name="uq_user_username"),
        UniqueConstraint("household_id", "email", name="uq_user_email"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    username: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[UserRole] = mapped_column(String(16))

    # The Google address Cloudflare Access authenticates, stored lowercased — this is the
    # login identity for everyone, parent and kid alike (spec §12.1). Nullable only so a
    # legacy or retired row can exist without one; a row with no email cannot sign in.
    email: Mapped[str | None] = mapped_column(String(320), default=None)

    # Break-glass only: the single local admin password that works on the loopback port and
    # never through the tunnel (spec §12.1). Children never have one.
    password_hash: Mapped[str | None] = mapped_column(String(255), default=None)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.admin
