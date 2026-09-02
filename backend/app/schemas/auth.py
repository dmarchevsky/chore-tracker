from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import UserRole

# The break-glass password is the one credential that survives an outage of both
# Cloudflare and Google, and everyone on the wifi gets to try it (spec §12.1). The
# minimum lives here so the API and the bootstrap seed cannot drift apart on it.
BREAK_GLASS_MIN_LENGTH = 12


class BreakGlassLoginRequest(BaseModel):
    """The local admin password path — everyone else arrives via Cloudflare Access."""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class MeResponse(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    email: str | None
    role: UserRole
    csrf_token: str


class LogoutResponse(BaseModel):
    # None when the app is not behind Access (LAN/dev); the SPA then just reloads.
    access_logout_url: str | None = None


class AdminProfileRequest(BaseModel):
    """A parent editing their own sign-in details. Both fields optional; omit to leave."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    email: EmailStr | None = None


class BreakGlassPasswordRequest(BaseModel):
    new_password: str = Field(min_length=BREAK_GLASS_MIN_LENGTH, max_length=256)


class DevUser(BaseModel):
    """One entry in the dev sign-in picker. No email: the point of dev mode is that Google
    is not involved, and showing addresses would only suggest otherwise."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    display_name: str
    role: UserRole


class DevLoginRequest(BaseModel):
    user_id: uuid.UUID
