"""Cloudflare Access: the edge gate and the identity it hands the app (spec §12.1, §12.2)."""

from __future__ import annotations

import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.auth.cf_access import CfAccessMiddleware, _guarded, access_email

TEAM = "acme.cloudflareaccess.com"
AUD = "test-aud-tag"
ADMIN_AUD = "admin-aud-tag"
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
    app.add_middleware(CfAccessMiddleware, team_domain=TEAM, aud=f"{AUD},{ADMIN_AUD}")

    @app.get("/api/v1/admin/ping")
    async def _admin() -> dict:
        return {"ok": True}

    @app.get("/api/v1/occurrences")
    async def _kid(request: Request) -> dict:
        return {"email": access_email(request)}

    @app.get("/api/v1/checkin/{token}")
    async def _checkin(token: str) -> dict:
        return {"ok": True}

    @app.post("/api/v1/auth/login")
    async def _breakglass() -> dict:
        return {"ok": True}

    @app.get("/api/v1/health")
    async def _health() -> dict:
        return {"status": "ok"}

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


def test_guarded_paths():
    # Access now fronts the whole app, kids included (spec §12.2) — the old carve-out for
    # the kid surface is exactly the hole this change closes.
    assert _guarded("/api/v1/admin/jobs")
    assert _guarded("/api/v1/health/llm")
    assert _guarded("/api/v1/occurrences")
    assert _guarded("/api/v1/auth/me")
    # The three documented exemptions, each with no browser to redirect.
    assert not _guarded("/api/v1/health")
    assert not _guarded("/api/v1/checkin/abc123")
    assert not _guarded("/api/v1/auth/login")


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


async def test_the_kid_surface_is_guarded_too(client):
    async with client as c:
        anon = await c.get("/api/v1/occurrences")
        signed = await c.get("/api/v1/occurrences", headers={"Cf-Access-Jwt-Assertion": _token()})
    assert anon.status_code == 403
    assert signed.status_code == 200
    # The verified claim reaches the handler, which is what /auth/me turns into a session.
    assert signed.json()["email"] == "op@acme.com"


async def test_a_second_access_application_aud_is_accepted(client):
    """The admin-scoped Access app issues its own AUD tag; both must verify."""
    async with client as c:
        r = await c.get(
            "/api/v1/admin/ping", headers={"Cf-Access-Jwt-Assertion": _token(aud=ADMIN_AUD)}
        )
    assert r.status_code == 200


async def test_a_spoofed_identity_header_is_not_an_identity(client):
    """CF-Access-Authenticated-User-Email is a plain header; only the JWT counts."""
    async with client as c:
        r = await c.get(
            "/api/v1/occurrences",
            headers={"CF-Access-Authenticated-User-Email": "parent@example.com"},
        )
    assert r.status_code == 403


async def test_exempt_paths_need_no_assertion(client):
    async with client as c:
        health = await c.get("/api/v1/health")
        checkin = await c.get("/api/v1/checkin/some-token")
        breakglass = await c.post("/api/v1/auth/login")
    assert health.status_code == 200
    # An iOS Shortcut cannot carry an Access session — this path is token-authed instead.
    assert checkin.status_code == 200
    # Break-glass is kept off the internet by the Caddy front door, not by Access.
    assert breakglass.status_code == 200


def test_middleware_absent_when_unconfigured(monkeypatch):
    from app.config import get_settings
    from app.main import create_app

    monkeypatch.delenv("CF_ACCESS_TEAM_DOMAIN", raising=False)
    monkeypatch.delenv("CF_ACCESS_AUD", raising=False)
    get_settings.cache_clear()
    app = create_app()
    get_settings.cache_clear()
    assert not any(m.cls is CfAccessMiddleware for m in app.user_middleware)


async def test_a_rejection_logs_what_the_token_actually_claimed(client, caplog):
    """PyJWT says "Invalid issuer" without naming either side; the log must name both."""
    import logging

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="chorekeeper.api"):
        async with client as c:
            r = await c.get(
                "/api/v1/occurrences",
                headers={"Cf-Access-Jwt-Assertion": _token(iss="https://someone-else.example")},
            )
    assert r.status_code == 403
    (rec,) = [r for r in caplog.records if getattr(r, "event", "") == "cf_access.rejected"]
    assert rec.token_iss == "https://someone-else.example"
    assert rec.expected_iss == f"https://{TEAM}"
    assert ADMIN_AUD in rec.expected_aud
