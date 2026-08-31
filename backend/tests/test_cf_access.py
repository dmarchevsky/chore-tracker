"""Cloudflare Access enforcement on the admin surface (spec §12.2)."""

from __future__ import annotations

import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.auth.cf_access import CfAccessMiddleware, _guarded

TEAM = "acme.cloudflareaccess.com"
AUD = "test-aud-tag"
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def _stub_jwks(monkeypatch):
    monkeypatch.setattr(
        "app.auth.cf_access.jwt.PyJWKClient.get_signing_key_from_jwt",
        lambda self, token: SimpleNamespace(key=_KEY.public_key()),
    )


def _token(*, aud: str = AUD, iss: str = f"https://{TEAM}", exp_delta: int = 300) -> str:
    return jwt.encode(
        {"aud": aud, "iss": iss, "exp": int(time.time()) + exp_delta, "email": "op@acme.com"},
        _KEY,
        algorithm="RS256",
    )


@pytest.fixture
def client():
    app = FastAPI()
    app.add_middleware(CfAccessMiddleware, team_domain=TEAM, aud=AUD)

    @app.get("/api/v1/admin/ping")
    async def _admin() -> dict:
        return {"ok": True}

    @app.get("/api/v1/health")
    async def _health() -> dict:
        return {"status": "ok"}

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


def test_guarded_paths():
    assert _guarded("/api/v1/admin/jobs")
    assert _guarded("/api/v1/health/llm")
    assert not _guarded("/api/v1/health")
    assert not _guarded("/api/v1/occurrences")


async def test_valid_assertion_passes(client):
    async with client as c:
        r = await c.get("/api/v1/admin/ping", headers={"Cf-Access-Jwt-Assertion": _token()})
    assert r.status_code == 200


async def test_missing_assertion_is_403(client):
    async with client as c:
        r = await c.get("/api/v1/admin/ping")
    assert r.status_code == 403


async def test_wrong_audience_is_403(client):
    async with client as c:
        r = await c.get(
            "/api/v1/admin/ping", headers={"Cf-Access-Jwt-Assertion": _token(aud="someone-else")}
        )
    assert r.status_code == 403


async def test_expired_assertion_is_403(client):
    async with client as c:
        r = await c.get(
            "/api/v1/admin/ping", headers={"Cf-Access-Jwt-Assertion": _token(exp_delta=-10)}
        )
    assert r.status_code == 403


async def test_non_admin_path_needs_no_assertion(client):
    async with client as c:
        r = await c.get("/api/v1/health")
    assert r.status_code == 200


def test_middleware_absent_when_unconfigured(monkeypatch):
    from app.config import get_settings
    from app.main import create_app

    monkeypatch.delenv("CF_ACCESS_TEAM_DOMAIN", raising=False)
    monkeypatch.delenv("CF_ACCESS_AUD", raising=False)
    get_settings.cache_clear()
    app = create_app()
    get_settings.cache_clear()
    assert not any(m.cls is CfAccessMiddleware for m in app.user_middleware)
