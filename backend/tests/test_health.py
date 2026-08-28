from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_health_ok(client):
    r = await client.get("/api/v1/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


async def test_health_llm_is_admin_only(client, admin_user, child_user, totp_now):
    assert (await client.get("/api/v1/health/llm")).status_code == 401

    await client.post("/api/v1/auth/login", json={"username": "alice", "password": "alice-pass"})
    assert (await client.get("/api/v1/health/llm")).status_code == 403

    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "parent", "password": "parent-pass", "totp_code": totp_now()},
    )
    assert r.status_code == 200
    assert (await client.get("/api/v1/health/llm")).status_code == 200


async def test_security_headers_present(client):
    r = await client.get("/api/v1/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "content-security-policy" in r.headers
