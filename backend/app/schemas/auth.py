from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.models import UserRole


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    totp_code: str | None = Field(default=None, max_length=8)


class MeResponse(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    role: UserRole
    csrf_token: str
    totp_enrolled: bool


class TotpEnrollResponse(BaseModel):
    secret: str
    provisioning_uri: str


class TotpConfirmRequest(BaseModel):
    totp_code: str = Field(min_length=6, max_length=8)
