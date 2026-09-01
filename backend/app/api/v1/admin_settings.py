"""Runtime household settings — vision-LLM connection + verification banding (spec §7.2).

Values are stored on ``household_settings`` and override the ``.env`` defaults. The API key
is write-only: reads report ``api_key_set`` but never the value.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from app.auth.deps import AdminUser, DbDep
from app.auth.passwords import hash_password
from app.config import get_settings
from app.schemas.auth import BreakGlassPasswordRequest
from app.services import audit
from app.services.llm_config import (
    ensure_settings_row,
    get_llm_config,
    get_verification_defaults,
    probe_models,
)

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
