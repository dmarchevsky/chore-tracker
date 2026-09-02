"""Internet-exposure hardening: Host allow-list, Secure cookie, no debug endpoints (spec §12.2)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import create_app


@pytest.fixture
def fresh_app(monkeypatch):
    def _build(**env: str):
        # A prod app refuses to start on the default session secret, which every test here
        # but that one would otherwise trip over. Supply a real-looking one by default and
        # let a test override it to assert the refusal.
        env.setdefault("SESSION_SECRET", "0" * 64)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        get_settings.cache_clear()
        return create_app()

    yield _build
    get_settings.cache_clear()


async def _get(app, path: str, **kw):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        return await c.get(path, **kw)


async def test_trusted_host_rejects_unknown_host(fresh_app):
    app = fresh_app(ALLOWED_HOSTS="chores.example.com")
    ok = await _get(app, "/api/v1/health", headers={"host": "chores.example.com"})
    assert ok.status_code == 200
    bad = await _get(app, "/api/v1/health", headers={"host": "evil.example.com"})
    assert bad.status_code == 400


async def test_no_host_check_when_allowed_hosts_empty(fresh_app):
    app = fresh_app(ALLOWED_HOSTS="")
    r = await _get(app, "/api/v1/health", headers={"host": "anything.example.com"})
    assert r.status_code == 200


async def test_docs_disabled_in_prod(fresh_app):
    app = fresh_app(ENVIRONMENT="prod")
    assert (await _get(app, "/docs")).status_code == 404
    assert (await _get(app, "/openapi.json")).status_code == 404


async def test_hsts_emitted_in_prod(fresh_app):
    app = fresh_app(ENVIRONMENT="prod")
    r = await _get(app, "/api/v1/health")
    assert "preload" in r.headers.get("strict-transport-security", "")


def test_session_cookie_is_secure_in_prod(fresh_app, monkeypatch):
    fresh_app(ENVIRONMENT="prod")  # primes get_settings()
    from starlette.responses import Response

    from app.api.v1.auth import _set_session_cookie

    resp = Response()
    _set_session_cookie(resp, "sid-123", max_age=3600)
    assert "Secure" in resp.headers["set-cookie"]


def test_session_cookie_not_secure_in_dev(fresh_app):
    fresh_app(ENVIRONMENT="dev", COOKIE_SECURE="false")
    from starlette.responses import Response

    from app.api.v1.auth import _set_session_cookie

    resp = Response()
    _set_session_cookie(resp, "sid-123", max_age=3600)
    assert "Secure" not in resp.headers["set-cookie"]


# --- DEV_AUTH must never boot outside dev (spec §12.1) --------------------------------


def test_dev_auth_refuses_to_start_in_prod(fresh_app):
    """A passwordless production stack looks exactly like a working one from the outside,
    so the only safe place to catch this is before the port is bound."""
    with pytest.raises(RuntimeError, match="DEV_AUTH"):
        fresh_app(DEV_AUTH="true", ENVIRONMENT="prod")


def test_prod_refuses_to_start_on_the_default_session_secret(fresh_app):
    """It signs the media URLs too, and its default is in this repo — a prod app running on
    it hands out forgeable links while looking perfectly healthy."""
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        fresh_app(ENVIRONMENT="prod", SESSION_SECRET="dev-insecure-change-me")


def test_dev_keeps_the_default_session_secret(fresh_app):
    """A fresh checkout has to start with no configuration at all."""
    app = fresh_app(ENVIRONMENT="dev", SESSION_SECRET="dev-insecure-change-me")
    assert app is not None


def test_dev_auth_refuses_to_start_alongside_cloudflare_access(fresh_app):
    with pytest.raises(RuntimeError, match="DEV_AUTH"):
        fresh_app(
            DEV_AUTH="true",
            ENVIRONMENT="dev",
            CF_ACCESS_TEAM_DOMAIN="acme.cloudflareaccess.com",
            CF_ACCESS_AUD="aud-tag",
        )
