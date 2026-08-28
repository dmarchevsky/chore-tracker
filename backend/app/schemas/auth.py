from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, model_validator

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


class TotpResetRequest(BaseModel):
    """Re-auth to drop the current authenticator so a new one can be enrolled."""

    password: str | None = Field(default=None, max_length=256)
    totp_code: str | None = Field(default=None, max_length=8)

    @model_validator(mode="after")
    def _exactly_one(self) -> TotpResetRequest:
        if bool(self.password) == bool(self.totp_code):
            raise ValueError("provide exactly one of password or totp_code")
        return self
