from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.models import UserRole


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


class BreakGlassPasswordRequest(BaseModel):
    new_password: str = Field(min_length=12, max_length=256)
