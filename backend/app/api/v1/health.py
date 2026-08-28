"""Liveness + dependency probes (spec §10)."""

from __future__ import annotations

import httpx
from fastapi import APIRouter
from sqlalchemy import text

from app.auth.deps import AdminUser, DbDep
from app.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(db: DbDep) -> dict[str, str]:
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/health/llm")
async def health_llm(_: AdminUser) -> dict[str, object]:
    """VLM reachability — admin-only; the plain liveness probe is `/health` (spec §10)."""
    s = get_settings()
    url = s.llm_vision_base_url.rstrip("/") + "/models"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
        return {"reachable": resp.status_code < 500, "status_code": resp.status_code}
    except httpx.HTTPError as exc:
        return {"reachable": False, "error": str(exc)}
