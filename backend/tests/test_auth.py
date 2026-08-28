"""Phase 1 acceptance: admin (with TOTP) and child accounts can log in."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _login(client, **body):
    return await client.post("/api/v1/auth/login", json=body)


async def test_admin_login_requires_totp(client, admin_user, totp_now):
    r = await _login(client, username="parent", password="parent-pass")
    assert r.status_code == 401

    r = await _login(client, username="parent", password="parent-pass", totp_code=totp_now())
    assert r.status_code == 200
    data = r.json()
    assert data["role"] == "admin"
    assert data["csrf_token"]
    assert client.cookies.get("ck_session")


async def test_admin_wrong_totp_rejected(client, admin_user):
    r = await _login(client, username="parent", password="parent-pass", totp_code="000000")
    assert r.status_code == 401


async def test_child_login_no_totp(client, child_user):
    r = await _login(client, username="alice", password="alice-pass")
    assert r.status_code == 200
    assert r.json()["role"] == "child"


async def test_bad_password_rejected(client, child_user):
    r = await _login(client, username="alice", password="nope")
    assert r.status_code == 401


async def test_me_and_logout_roundtrip(client, child_user):
    await _login(client, username="alice", password="alice-pass")

    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["username"] == "alice"
    csrf = me.json()["csrf_token"]

    out = await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert out.status_code == 204

    me2 = await client.get("/api/v1/auth/me")
    assert me2.status_code == 401


async def test_fresh_admin_bootstraps_totp(client, admin_no_totp):
    # Not-yet-enrolled admin logs in with password alone, then enrolls + confirms.
    r = await _login(client, username="freshadmin", password="fresh-pass")
    assert r.status_code == 200
    csrf = r.json()["csrf_token"]

    enroll = await client.post("/api/v1/auth/totp/enroll", headers={"X-CSRF-Token": csrf})
    assert enroll.status_code == 200
    secret = enroll.json()["secret"]

    import pyotp

    confirm = await client.post(
        "/api/v1/auth/totp/confirm",
        json={"totp_code": pyotp.TOTP(secret).now()},
        headers={"X-CSRF-Token": csrf},
    )
    assert confirm.status_code == 200
    assert confirm.json()["totp_enrolled"] is True

    # Subsequent login now demands the code.
    await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    r = await _login(client, username="freshadmin", password="fresh-pass")
    assert r.status_code == 401
    r = await _login(
        client, username="freshadmin", password="fresh-pass", totp_code=pyotp.TOTP(secret).now()
    )
    assert r.status_code == 200


async def test_totp_reset_with_password_lets_admin_re_enroll(client, admin_user, totp_now):
    r = await _login(client, username="parent", password="parent-pass", totp_code=totp_now())
    csrf = r.json()["csrf_token"]

    reset = await client.post(
        "/api/v1/auth/totp/reset",
        json={"password": "parent-pass"},
        headers={"X-CSRF-Token": csrf},
    )
    assert reset.status_code == 200
    assert reset.json()["totp_enrolled"] is False

    # password alone now logs in (bootstrap window) and enrollment can start again
    await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    r = await _login(client, username="parent", password="parent-pass")
    assert r.status_code == 200
    enroll = await client.post(
        "/api/v1/auth/totp/enroll", headers={"X-CSRF-Token": r.json()["csrf_token"]}
    )
    assert enroll.status_code == 200


async def test_totp_reset_wrong_password_rejected(client, admin_user, totp_now):
    r = await _login(client, username="parent", password="parent-pass", totp_code=totp_now())
    csrf = r.json()["csrf_token"]
    bad = await client.post(
        "/api/v1/auth/totp/reset",
        json={"password": "not-it"},
        headers={"X-CSRF-Token": csrf},
    )
    assert bad.status_code == 401
    assert (await client.get("/api/v1/auth/me")).json()["totp_enrolled"] is True


async def test_totp_reset_forbidden_for_child(client, child_user):
    r = await _login(client, username="alice", password="alice-pass")
    csrf = r.json()["csrf_token"]
    bad = await client.post(
        "/api/v1/auth/totp/reset",
        json={"password": "alice-pass"},
        headers={"X-CSRF-Token": csrf},
    )
    assert bad.status_code == 403


async def test_login_ip_rate_limited(client, child_user):
    # 10 requests/min/IP (spec §12.1); the 11th is throttled regardless of validity.
    for _ in range(10):
        await _login(client, username="alice", password="wrong")
    r = await _login(client, username="alice", password="wrong")
    assert r.status_code == 429


async def test_account_backoff_after_failures(client, child_user):
    for _ in range(4):
        await _login(client, username="alice", password="wrong")
    # Backoff engaged; even the correct password is deferred.
    r = await _login(client, username="alice", password="alice-pass")
    assert r.status_code == 429
