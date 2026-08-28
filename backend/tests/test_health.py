from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_health_ok(client):
    r = await client.get("/api/v1/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


async def test_security_headers_present(client):
    r = await client.get("/api/v1/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "content-security-policy" in r.headers
