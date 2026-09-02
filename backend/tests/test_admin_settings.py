"""Phase 6: runtime LLM / verification settings (spec §7.2)."""

from __future__ import annotations

import httpx
import pytest
import respx
from tests.helpers import sign_in

from app.services.llm_config import get_llm_config

pytestmark = pytest.mark.asyncio


async def _admin(client) -> dict:
    r = await sign_in(client, "parent@example.com")
    assert r.status_code == 200
    return {"X-CSRF-Token": r.json()["csrf_token"]}


async def test_get_shows_env_defaults(client, admin_user, household):
    h = await _admin(client)
    body = (await client.get("/api/v1/admin/settings", headers=h)).json()
    assert body["llm"]["base_url"] == "http://llm-vision:8081/v1"
    assert body["llm"]["api_key_set"] is False
    assert body["source"]["llm_base_url"] == "env"


async def test_put_overrides_then_null_clears(client, admin_user, household, db_session):
    h = await _admin(client)

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


async def test_thresholds_are_overridable(client, admin_user, household):
    h = await _admin(client)
    r = await client.patch(
        "/api/v1/admin/settings",
        json={"auto_pass_threshold": 0.7, "auto_fail_threshold": 0.2},
        headers=h,
    )
    v = r.json()["verification"]
    assert v["auto_pass_threshold"] == pytest.approx(0.7)
    assert v["auto_fail_threshold"] == pytest.approx(0.2)


@respx.mock
async def test_models_proxy_parses_openai_list(client, admin_user, household):
    h = await _admin(client)
    respx.get("http://probe.test/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "gemma3"}, {"id": "qwen3-vl"}]})
    )
    r = await client.get("/api/v1/admin/llm/models?base_url=http://probe.test/v1", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["reachable"] is True and body["models"] == ["gemma3", "qwen3-vl"]


async def test_settings_are_admin_only(client, child_user):
    await sign_in(client, "alice@example.com")
    assert (await client.get("/api/v1/admin/settings")).status_code == 403


# --- the vision endpoint is admin-writable, so its shape is checked (spec §7.2) ---------


async def test_settings_rejects_a_base_url_that_is_not_http(client, admin_user):
    """A typo here is a 422 the parent can read, rather than a verification that fails open
    to NEEDS_REVIEW hours later with an error nobody connects to this screen."""
    h = await _admin(client)
    for bad in ("file:///etc/passwd", "llm-vision:8081/v1", "gopher://box/"):
        r = await client.patch("/api/v1/admin/settings", json={"llm_base_url": bad}, headers=h)
        assert r.status_code == 422, bad


async def test_settings_accepts_a_lan_endpoint(client, admin_user):
    """An internal address is the *point* of this setting — a llama-server on the LAN."""
    h = await _admin(client)
    r = await client.patch(
        "/api/v1/admin/settings", json={"llm_base_url": "http://llm-box.lan:8081/v1"}, headers=h
    )
    assert r.status_code == 200
    assert r.json()["llm"]["base_url"] == "http://llm-box.lan:8081/v1"


async def test_probing_a_non_http_url_is_data_not_a_request(client, admin_user):
    h = await _admin(client)
    r = await client.get("/api/v1/admin/llm/models?base_url=file:///etc/passwd", headers=h)
    assert r.status_code == 200
    assert r.json()["reachable"] is False
    assert r.json()["models"] == []


# --- a parent's own sign-in details (spec §12.1) ---------------------------------------


async def test_admin_can_change_their_own_google_address(client, db_session, admin_user):
    """No other endpoint can: PATCH /children/{id} 404s on an admin row. Until this existed,
    a wrong ADMIN_EMAIL meant Access vouched for someone the app had never heard of and the
    only fix was SQL on the host."""
    h = await _admin(client)
    r = await client.patch(
        "/api/v1/admin/profile", json={"email": "New.Parent@Example.com"}, headers=h
    )
    assert r.status_code == 200
    assert r.json()["email"] == "new.parent@example.com"  # stored lowercased
    assert r.json()["signed_out"] is True


async def test_changing_the_address_revokes_the_session(client, admin_user):
    """Access is authoritative about who is at the keyboard, so a session minted for the old
    identity must not outlive it — the same rule the kid path already follows."""
    h = await _admin(client)
    await client.patch("/api/v1/admin/profile", json={"email": "moved@example.com"}, headers=h)

    assert (await client.get("/api/v1/admin/settings", headers=h)).status_code == 401


async def test_renaming_without_touching_the_address_keeps_you_signed_in(client, admin_user):
    h = await _admin(client)
    r = await client.patch("/api/v1/admin/profile", json={"display_name": "Mum"}, headers=h)
    assert r.status_code == 200
    assert r.json()["signed_out"] is False
    assert (await client.get("/api/v1/admin/settings", headers=h)).status_code == 200


async def test_resaving_the_same_address_is_not_a_conflict_with_itself(client, admin_user):
    h = await _admin(client)
    r = await client.patch("/api/v1/admin/profile", json={"email": admin_user.email}, headers=h)
    assert r.status_code == 200
    assert r.json()["signed_out"] is False


async def test_an_address_a_kid_already_uses_is_refused(client, admin_user, child_user):
    h = await _admin(client)
    r = await client.patch("/api/v1/admin/profile", json={"email": child_user.email}, headers=h)
    assert r.status_code == 409


async def test_a_child_cannot_reach_the_profile_endpoint(client, child_user):
    r = await sign_in(client, "alice@example.com")
    h = {"X-CSRF-Token": r.json()["csrf_token"]}
    assert (
        await client.patch("/api/v1/admin/profile", json={"display_name": "x"}, headers=h)
    ).status_code == 403
