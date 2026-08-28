"""Phase 6: runtime LLM / verification settings (spec §7.2)."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.services.llm_config import get_llm_config

pytestmark = pytest.mark.asyncio


async def _admin(client, totp_now) -> dict:
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "parent", "password": "parent-pass", "totp_code": totp_now()},
    )
    assert r.status_code == 200
    return {"X-CSRF-Token": r.json()["csrf_token"]}


async def test_get_shows_env_defaults(client, admin_user, household, totp_now):
    h = await _admin(client, totp_now)
    body = (await client.get("/api/v1/admin/settings", headers=h)).json()
    assert body["llm"]["base_url"] == "http://llm-vision:8081/v1"
    assert body["llm"]["api_key_set"] is False
    assert body["source"]["llm_base_url"] == "env"


async def test_put_overrides_then_null_clears(client, admin_user, household, totp_now, db_session):
    h = await _admin(client, totp_now)

    put = await client.patch(
        "/api/v1/admin/settings",
        json={"llm_base_url": "http://box:9000/v1", "llm_model": "qwen3-vl", "llm_api_key": "sk"},
        headers=h,
    )
    assert put.status_code == 200
    body = put.json()
    assert body["llm"]["base_url"] == "http://box:9000/v1"
    assert body["llm"]["model"] == "qwen3-vl"
    assert body["llm"]["api_key_set"] is True
    assert body["source"]["llm_model"] == "db"

    # the resolver a worker would use reflects the override
    cfg = await get_llm_config(db_session)
    assert cfg.base_url == "http://box:9000/v1" and cfg.model == "qwen3-vl" and cfg.api_key == "sk"

    cleared = await client.patch("/api/v1/admin/settings", json={"llm_model": None}, headers=h)
    assert cleared.json()["source"]["llm_model"] == "env"
    assert cleared.json()["llm"]["model"] == ""  # back to the env default


async def test_thresholds_are_overridable(client, admin_user, household, totp_now):
    h = await _admin(client, totp_now)
    r = await client.patch(
        "/api/v1/admin/settings",
        json={"auto_pass_threshold": 0.7, "auto_fail_threshold": 0.2},
        headers=h,
    )
    v = r.json()["verification"]
    assert v["auto_pass_threshold"] == pytest.approx(0.7)
    assert v["auto_fail_threshold"] == pytest.approx(0.2)


@respx.mock
async def test_models_proxy_parses_openai_list(client, admin_user, household, totp_now):
    h = await _admin(client, totp_now)
    respx.get("http://probe.test/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "gemma3"}, {"id": "qwen3-vl"}]})
    )
    r = await client.get("/api/v1/admin/llm/models?base_url=http://probe.test/v1", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["reachable"] is True and body["models"] == ["gemma3", "qwen3-vl"]


async def test_settings_are_admin_only(client, child_user):
    await client.post("/api/v1/auth/login", json={"username": "alice", "password": "alice-pass"})
    assert (await client.get("/api/v1/admin/settings")).status_code == 403
