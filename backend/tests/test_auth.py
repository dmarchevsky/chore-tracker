"""Sign-in: Google via Cloudflare Access, plus the break-glass admin password (spec §12.1)."""

from __future__ import annotations

import logging

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


async def test_the_address_turned_away_is_logged_not_only_returned(client, caplog, admin_user):
    """A failed sign-in has to leave a trace with the address on it.

    The phone that fails is in another room, and until this line existed the only record was
    an access-log 403 naming no account — so "why can't my kid sign in" could not be answered
    from the logs at all.
    """
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="chorekeeper.api"):
        r = await sign_in(client, "stranger@example.com")
    assert r.status_code == 403
    (rec,) = [x for x in caplog.records if getattr(x, "event", "") == "auth.not_a_member"]
    assert rec.email == "stranger@example.com"
    assert rec.inactive is False


async def test_a_deactivated_member_is_logged_as_one(client, caplog, db_session, child_user):
    """Deactivated and never-heard-of answer the same 403 on purpose, but they are different
    problems for the parent, so the log has to tell them apart."""
    child_user.is_active = False
    await db_session.commit()
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="chorekeeper.api"):
        assert (await sign_in(client, "alice@example.com")).status_code == 403
    (rec,) = [x for x in caplog.records if getattr(x, "event", "") == "auth.not_a_member"]
    assert rec.inactive is True


async def test_a_probe_with_no_identity_says_which_door_it_came_through(client, caplog, admin_user):
    """Behind Access a 401 here should be unreachable, so if one shows up the door it arrived
    on is the whole diagnosis."""
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="chorekeeper.api"):
        assert (await client.get("/api/v1/auth/me")).status_code == 401
    (rec,) = [x for x in caplog.records if getattr(x, "event", "") == "auth.no_identity"]
    assert rec.lan_door is False


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


async def test_logout_returns_the_team_domain_url_that_actually_ends_the_session(
    client, admin_user, monkeypatch
):
    """The app host's /cdn-cgi/access/logout answers 200 with a bare Cloudflare page: it
    clears no cookie and offers no way back, stranding the visitor still signed in. Only
    the team-domain form with ?returnTo= expires CF_Authorization and redirects home."""
    from app.config import get_settings

    monkeypatch.setenv("CF_ACCESS_TEAM_DOMAIN", "acme.cloudflareaccess.com")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://chores.example.com")
    get_settings.cache_clear()
    try:
        await sign_in(client, "parent@example.com")
        url = (await client.post("/api/v1/auth/logout")).json()["access_logout_url"]
    finally:
        get_settings.cache_clear()

    assert url.startswith("https://acme.cloudflareaccess.com/cdn-cgi/access/logout?")
    assert "returnTo=https%3A%2F%2Fchores.example.com%2F" in url


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


async def test_the_lan_door_gets_a_non_secure_cookie(client, admin_user, monkeypatch):
    """A Secure cookie is never sent back over the LAN door's plain HTTP, so break-glass
    would log in and then lose the session on the very next request (spec §12.1)."""
    from app.config import get_settings

    monkeypatch.setenv("COOKIE_SECURE", "true")
    get_settings.cache_clear()
    try:
        lan = await client.post(
            "/api/v1/auth/login",
            json={"username": "parent", "password": "parent-pass"},
            headers={"X-CK-Door": "lan"},
        )
        tunnel = await client.post(
            "/api/v1/auth/login",
            json={"username": "parent", "password": "parent-pass"},
            headers={"X-CK-Door": "tunnel"},
        )
    finally:
        get_settings.cache_clear()

    assert "secure" not in lan.headers["set-cookie"].lower()
    # Everywhere else the cookie stays Secure — the exemption is the door, not the build.
    assert "secure" in tunnel.headers["set-cookie"].lower()


# --- Dev-mode sign-in (DEV_AUTH) -----------------------------------------------------
# The dev stack has no Cloudflare in front of it and no break-glass behind it, so this
# picker is the whole way in. Everything here is about it staying strictly local.


@pytest.fixture
def dev_auth(monkeypatch):
    """Turn DEV_AUTH on for one test, and back off however the test ends."""
    from app.config import get_settings

    monkeypatch.setenv("DEV_AUTH", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_dev_routes_do_not_exist_without_dev_auth(client, admin_user):
    """Not 403 — 404. A route that answers "forbidden" tells an internet scanner the
    passwordless door is there and only bolted; this one is not there at all."""
    assert (await client.get("/api/v1/auth/dev/users")).status_code == 404
    r = await client.post("/api/v1/auth/dev/login", json={"user_id": str(admin_user.id)})
    assert r.status_code == 404


async def test_dev_users_lists_the_household_parents_first(
    client, admin_user, child_user, dev_auth
):
    r = await client.get("/api/v1/auth/dev/users")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [u["username"] for u in body] == ["parent", "alice"]
    # No addresses: Google is not part of dev sign-in and showing them would imply it is.
    assert "email" not in body[0]


async def test_dev_users_omits_deactivated_members(client, db_session, child_user, dev_auth):
    child_user.is_active = False
    await db_session.commit()
    assert (await client.get("/api/v1/auth/dev/users")).json() == []


async def test_dev_login_mints_a_real_session(client, child_user, dev_auth):
    r = await client.post("/api/v1/auth/dev/login", json={"user_id": str(child_user.id)})
    assert r.status_code == 200, r.text
    assert r.json()["username"] == "alice"
    assert client.cookies.get(SESSION_COOKIE)
    # The same session machinery production uses — the cookie alone carries the next call.
    assert (await client.get("/api/v1/auth/me")).json()["id"] == r.json()["id"]


async def test_dev_login_refuses_a_deactivated_member(client, db_session, child_user, dev_auth):
    child_user.is_active = False
    await db_session.commit()
    r = await client.post("/api/v1/auth/dev/login", json={"user_id": str(child_user.id)})
    assert r.status_code == 404


async def test_break_glass_is_gone_in_dev_mode(client, admin_user, dev_auth):
    """One sign-in path per mode. A second one that only exists locally is a second one
    that can quietly stop matching what production does."""
    r = await client.post(
        "/api/v1/auth/login", json={"username": "parent", "password": "parent-pass"}
    )
    assert r.status_code == 404
