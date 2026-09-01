from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import UserRole


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=120)
    # This endpoint only mints child accounts (spec §4.3); default so callers can omit it.
    role: UserRole = UserRole.child
    # The kid's Google address. It must also be listed in the Cloudflare Access policy —
    # adding it here alone gets them a 403 at the edge (docs/remote-access.md).
    email: EmailStr = Field(max_length=320)


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    email: EmailStr | None = Field(default=None, max_length=320)
    is_active: bool | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    display_name: str
    email: str | None
    role: UserRole
    is_active: bool


class CheckinTokenOut(BaseModel):
    token: str
    webhook_url: str
    last_used_at: datetime | None
    stale: bool
