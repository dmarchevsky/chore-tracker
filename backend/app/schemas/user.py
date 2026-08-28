from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import UserRole


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=120)
    # This endpoint only mints child accounts (spec §4.3); default so callers can omit it.
    role: UserRole = UserRole.child
    password: str = Field(min_length=4, max_length=256)


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None


class PasswordReset(BaseModel):
    # Admin resets a kid's password from the panel (spec §15 Q4 default).
    new_password: str = Field(min_length=4, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    display_name: str
    role: UserRole
    is_active: bool
    totp_enrolled: bool


class CheckinTokenOut(BaseModel):
    token: str
    webhook_url: str
    last_used_at: datetime | None
    stale: bool
