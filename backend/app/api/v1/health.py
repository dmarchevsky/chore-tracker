"""Liveness + dependency probes (spec §10)."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.auth.deps import AdminUser, DbDep
from app.services.llm_config import (
    get_decider_config,
    get_llm_config,
    get_verifier_backend,
    probe_models,
)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(db: DbDep) -> dict[str, str]:
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/health/llm")
async def health_llm(db: DbDep, _: AdminUser) -> dict[str, object]:
    """VLM reachability + model list — admin-only; the plain liveness probe is `/health`.

    With the decider chosen, ``decider`` reports its endpoint too; the VLM stays listed
    because it is the fallback (spec §7.2).
    """
    cfg = await get_llm_config(db)
    backend = await get_verifier_backend(db)
    out: dict[str, object] = {
        "backend": backend,
        "base_url": cfg.base_url,
        "model": cfg.model,
        **await probe_models(cfg.base_url, cfg.api_key),
    }
    if backend == "decider":
        dcfg = await get_decider_config(db)
        out["decider"] = {
            "base_url": dcfg.base_url,
            "model": dcfg.model,
            **await probe_models(dcfg.base_url, ""),
        }
    return out
