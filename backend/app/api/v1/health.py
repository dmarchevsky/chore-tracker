"""Liveness + dependency probes (spec §10)."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.auth.deps import AdminUser, DbDep
from app.services.llm_config import get_llm_config, probe_models

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(db: DbDep) -> dict[str, str]:
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/health/llm")
async def health_llm(db: DbDep, _: AdminUser) -> dict[str, object]:
    """VLM reachability + model list — admin-only; the plain liveness probe is `/health`."""
    cfg = await get_llm_config(db)
    return {
        "base_url": cfg.base_url,
        "model": cfg.model,
        **await probe_models(cfg.base_url, cfg.api_key),
    }
