"""Effective vision-LLM configuration: DB overrides layered over environment defaults.

``HouseholdSettings`` rows hold optional overrides written by the admin settings screen;
anything left ``NULL`` falls through to ``app.config.Settings`` (the ``.env`` values). The
row is created lazily so a fresh install just uses the environment.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models import Household, HouseholdSettings


@dataclass(frozen=True)
class LlmConfig:
    base_url: str
    model: str
    api_key: str
    timeout_s: int
    max_retries: int

    @classmethod
    def from_settings(cls, s: Settings) -> LlmConfig:
        return cls(
            base_url=s.llm_vision_base_url,
            model=s.llm_vision_model,
            api_key=s.llm_vision_api_key,
            timeout_s=s.llm_timeout_s,
            max_retries=s.llm_max_retries,
        )


async def ensure_settings_row(db: AsyncSession) -> HouseholdSettings:
    row = (await db.execute(select(HouseholdSettings).limit(1))).scalar_one_or_none()
    if row is None:
        household_id = (await db.execute(select(Household.id).limit(1))).scalar_one()
        row = HouseholdSettings(household_id=household_id)
        db.add(row)
        await db.flush()
    return row


async def get_llm_config(db: AsyncSession, *, settings: Settings | None = None) -> LlmConfig:
    s = settings or get_settings()
    row = await ensure_settings_row(db)
    return LlmConfig(
        base_url=row.llm_base_url or s.llm_vision_base_url,
        model=row.llm_model or s.llm_vision_model,
        api_key=row.llm_api_key or s.llm_vision_api_key,
        timeout_s=row.llm_timeout_s if row.llm_timeout_s is not None else s.llm_timeout_s,
        max_retries=(row.llm_max_retries if row.llm_max_retries is not None else s.llm_max_retries),
    )


async def get_verification_defaults(
    db: AsyncSession, *, settings: Settings | None = None
) -> tuple[float, float]:
    """Global auto-pass / auto-fail confidence bands (per-chore values still win)."""
    s = settings or get_settings()
    row = await ensure_settings_row(db)
    ap = row.auto_pass_threshold
    af = row.auto_fail_threshold
    return (
        float(ap) if ap is not None else s.auto_pass_threshold,
        float(af) if af is not None else s.auto_fail_threshold,
    )


async def probe_models(base_url: str, api_key: str, *, timeout_s: float = 5.0) -> dict:
    """Hit the OpenAI-compatible ``GET /v1/models`` and return the id list.

    Used by the admin settings screen to populate the model picker and by
    ``GET /health/llm``. Never raises — an unreachable endpoint is data, not an error.
    """
    url = base_url.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.get(url, headers=headers)
        models: list[str] = []
        if resp.status_code < 400:
            data = resp.json()
            models = [m["id"] for m in data.get("data", []) if isinstance(m, dict) and "id" in m]
        return {
            "reachable": resp.status_code < 500,
            "status_code": resp.status_code,
            "models": models,
        }
    except (httpx.HTTPError, ValueError) as exc:
        return {"reachable": False, "error": str(exc), "models": []}
