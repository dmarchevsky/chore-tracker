from __future__ import annotations

import pytest
from tests.helpers import sign_in

pytestmark = pytest.mark.asyncio


async def test_health_ok(client):
    r = await client.get("/api/v1/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


async def test_health_llm_is_admin_only(client, admin_user, child_user):
    assert (await client.get("/api/v1/health/llm")).status_code == 401

    await sign_in(client, "alice@example.com")
    assert (await client.get("/api/v1/health/llm")).status_code == 403

    r = await sign_in(client, "parent@example.com")
    assert r.status_code == 200
    assert (await client.get("/api/v1/health/llm")).status_code == 200


async def test_security_headers_present(client):
    r = await client.get("/api/v1/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "content-security-policy" in r.headers
