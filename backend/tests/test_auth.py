"""Sign-in: Google via Cloudflare Access, plus the break-glass admin password (spec §12.1)."""

from __future__ import annotations

import pytest
from tests.helpers import sign_in

from app.auth import SESSION_COOKIE

pytestmark = pytest.mark.asyncio


async def test_access_verified_email_mints_a_session(client, admin_user):
    """The Access assertion *is* the login — there is no form for a parent to fill in."""
    r = await sign_in(client, "parent@example.com")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "parent@example.com"
    assert body["role"] == "admin"
    assert body["csrf_token"]
    assert client.cookies.get(SESSION_COOKIE)

    # The cookie carries the session from here; no further assertion is needed.
    again = await client.get("/api/v1/auth/me")
    assert again.status_code == 200
    assert again.json()["id"] == body["id"]


async def test_a_kid_signs_in_the_same_way(client, child_user):
    r = await sign_in(client, "alice@example.com")
    assert r.status_code == 200
    assert r.json()["role"] == "child"


async def test_the_address_is_matched_case_insensitively(client, child_user):
    assert (await sign_in(client, "Alice@Example.com".lower())).status_code == 200


async def test_an_unknown_google_account_is_named_in_the_error(client, admin_user):
    r = await sign_in(client, "stranger@example.com")
    assert r.status_code == 403
    # Naming the address is the point: the parent's next move is to paste this exact
    # string into Kids, and a generic "access denied" hides which account the phone used.
    assert "stranger@example.com" in r.json()["detail"]


async def test_a_deactivated_member_cannot_sign_in(client, db_session, child_user):
    child_user.is_active = False
    await db_session.commit()
    assert (await sign_in(client, "alice@example.com")).status_code == 403


async def test_no_session_and_no_assertion_is_401(client, admin_user):
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_logout_revokes_the_session_and_points_at_access(client, admin_user):
    await sign_in(client, "parent@example.com")
    out = await client.post("/api/v1/auth/logout")
    assert out.status_code == 200
    # Unset locally, so there is no edge session to end and nowhere to send the browser.
    assert out.json()["access_logout_url"] is None
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_break_glass_admin_password_works(client, admin_user):
    r = await client.post(
        "/api/v1/auth/login", json={"username": "parent", "password": "parent-pass"}
    )
    assert r.status_code == 200, r.text
    assert client.cookies.get(SESSION_COOKIE)


async def test_break_glass_rejects_a_bad_password(client, admin_user):
    r = await client.post("/api/v1/auth/login", json={"username": "parent", "password": "nope"})
    assert r.status_code == 401


async def test_break_glass_is_closed_to_children(client, child_user):
    """A kid has no password column at all; the role check must not depend on that."""
    r = await client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "alice-pass"}
    )
    assert r.status_code == 401


async def test_break_glass_is_ip_rate_limited(client, admin_user):
    for _ in range(10):
        await client.post("/api/v1/auth/login", json={"username": "parent", "password": "x"})
    r = await client.post("/api/v1/auth/login", json={"username": "parent", "password": "x"})
    assert r.status_code == 429


async def test_break_glass_backs_off_per_account(client, admin_user):
    from app.auth import ratelimit

    for _ in range(3):
        ratelimit.record_failure("parent")
    r = await client.post(
        "/api/v1/auth/login", json={"username": "parent", "password": "parent-pass"}
    )
    assert r.status_code == 429


async def test_admin_can_set_the_break_glass_password(client, admin_user):
    headers = {"X-CSRF-Token": (await sign_in(client, "parent@example.com")).json()["csrf_token"]}
    r = await client.post(
        "/api/v1/admin/break-glass-password",
        json={"new_password": "a-much-longer-passphrase"},
        headers=headers,
    )
    assert r.status_code == 204

    client.cookies.clear()
    logged_in = await client.post(
        "/api/v1/auth/login",
        json={"username": "parent", "password": "a-much-longer-passphrase"},
    )
    assert logged_in.status_code == 200
