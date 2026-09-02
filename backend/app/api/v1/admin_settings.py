"""Runtime household settings — vision-LLM connection, verification banding, and the
parent's own sign-in details (spec §7.2, §12.1).

Values are stored on ``household_settings`` and override the ``.env`` defaults. The API key
is write-only: reads report ``api_key_set`` but never the value.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.auth.deps import AdminUser, DbDep
from app.auth.passwords import hash_password
from app.auth.sessions import revoke_user_sessions
from app.config import get_settings
from app.schemas.auth import AdminProfileRequest, BreakGlassPasswordRequest
from app.services import audit
from app.services.llm_config import (
    LlmConfigError,
    ensure_settings_row,
    get_llm_config,
    get_verification_defaults,
    probe_models,
    validate_base_url,
)
from app.services.users import email_taken

router = APIRouter(prefix="/admin", tags=["admin"])


class SettingsUpdate(BaseModel):
    """Partial update: omit a field to leave it, send ``null`` to reset it to the env default."""

    model_config = ConfigDict(extra="forbid")

    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_timeout_s: int | None = Field(default=None, ge=1, le=600)
    llm_max_retries: int | None = Field(default=None, ge=0, le=5)
    auto_pass_threshold: float | None = Field(default=None, ge=0, le=1)
    auto_fail_threshold: float | None = Field(default=None, ge=0, le=1)

    @field_validator("llm_base_url")
    @classmethod
    def _check_base_url(cls, v: str | None) -> str | None:
        """Caught here so a typo is a 422 the parent can read, not a verification that
        quietly fails open hours later (spec §6.3)."""
        if v in (None, ""):
            return v
        try:
            return validate_base_url(v)
        except LlmConfigError as exc:
            raise ValueError(str(exc)) from exc


async def _view(db: DbDep) -> dict:
    row = await ensure_settings_row(db)
    cfg = await get_llm_config(db)
    ap, af = await get_verification_defaults(db)
    src = {
        "llm_base_url": "db" if row.llm_base_url else "env",
        "llm_model": "db" if row.llm_model else "env",
        "llm_api_key": "db" if row.llm_api_key else "env",
        "llm_timeout_s": "db" if row.llm_timeout_s is not None else "env",
        "llm_max_retries": "db" if row.llm_max_retries is not None else "env",
        "auto_pass_threshold": "db" if row.auto_pass_threshold is not None else "env",
        "auto_fail_threshold": "db" if row.auto_fail_threshold is not None else "env",
    }
    return {
        "llm": {
            "base_url": cfg.base_url,
            "model": cfg.model,
            "api_key_set": bool(cfg.api_key and cfg.api_key != "not-needed"),
            "timeout_s": cfg.timeout_s,
            "max_retries": cfg.max_retries,
        },
        "verification": {"auto_pass_threshold": ap, "auto_fail_threshold": af},
        "source": src,
    }


@router.get("/settings")
async def get_settings_view(db: DbDep, _: AdminUser) -> dict:
    return await _view(db)


@router.patch("/settings")
async def update_settings(payload: SettingsUpdate, db: DbDep, admin: AdminUser) -> dict:
    row = await ensure_settings_row(db)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        if key == "llm_api_key" and value == "":
            value = None  # empty string clears the override
        setattr(row, key, value)
    row.updated_by_user_id = admin.id
    await db.flush()

    await audit.record(
        db,
        actor=admin,
        action="settings.update",
        entity_type="household_settings",
        entity_id=row.id,
        after={k: ("***" if k == "llm_api_key" else v) for k, v in data.items()},
    )
    return await _view(db)


@router.get("/llm/models")
async def list_llm_models(
    db: DbDep,
    _: AdminUser,
    base_url: Annotated[str | None, Query()] = None,
    api_key: Annotated[str | None, Query()] = None,
) -> dict:
    """Probe an endpoint's ``GET /v1/models`` — the given one, or the effective config."""
    if base_url:
        return await probe_models(base_url, api_key or get_settings().llm_vision_api_key)
    cfg = await get_llm_config(db)
    return await probe_models(cfg.base_url, cfg.api_key)


@router.post("/break-glass-password", status_code=204)
async def set_break_glass_password(
    payload: BreakGlassPasswordRequest, db: DbDep, admin: AdminUser
) -> None:
    """Set the admin's own local password — the only password write path left (spec §12.1).

    It is the way back in when Cloudflare or Google is unavailable, and it is usable only
    from the host's loopback port, so it is long-minimum and never handed to a child.
    """
    admin.password_hash = hash_password(payload.new_password)
    await audit.record(
        db,
        actor=admin,
        action="breakglass.password.set",
        entity_type="user",
        entity_id=admin.id,
    )


@router.get("/profile")
async def get_profile(admin: AdminUser) -> dict:
    return {"username": admin.username, "display_name": admin.display_name, "email": admin.email}


@router.patch("/profile")
async def update_profile(payload: AdminProfileRequest, db: DbDep, admin: AdminUser) -> dict:
    """Change one's own display name and Google address (spec §12.1).

    A parent's address is the only one no other endpoint can touch — ``PATCH /children/{id}``
    is scoped to children — and until this existed, a wrong ``ADMIN_EMAIL`` meant Access
    vouched for someone the app had never heard of, with no way out but SQL on the host.

    Changing the address **signs you out**, exactly as it does for a kid: the session was
    minted for the old identity and Access is authoritative about who is at the keyboard. It
    cannot lock you out — the break-glass password is untouched, so the LAN door still opens
    — but sign back in as the new address, and put it on the Access policy first.
    """
    before = {"display_name": admin.display_name, "email": admin.email}
    if payload.display_name is not None:
        admin.display_name = payload.display_name

    signed_out = False
    if payload.email is not None:
        email = payload.email.strip().lower()
        if email != admin.email:
            if await email_taken(db, email, excluding=admin.id):
                raise HTTPException(
                    status.HTTP_409_CONFLICT, "that Google address is already in use"
                )
            admin.email = email
            signed_out = True

    await audit.record(
        db,
        actor=admin,
        action="admin.profile.update",
        entity_type="user",
        entity_id=admin.id,
        before=before,
        after={"display_name": admin.display_name, "email": admin.email},
    )
    # Revoked last: the audit row above is written as this admin, and revoking first would
    # leave the trail attributed to a session that no longer exists.
    if signed_out:
        await revoke_user_sessions(db, admin.id)
    return {
        "username": admin.username,
        "display_name": admin.display_name,
        "email": admin.email,
        "signed_out": signed_out,
    }
