"""Phase 1: admin CRUD over child accounts; children cannot reach admin endpoints."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from tests.helpers import sign_in

from app.auth import SESSION_COOKIE
from app.models import AuditLog

pytestmark = pytest.mark.asyncio


async def _admin_client(client, admin_user):
    r = await sign_in(client, "parent@example.com")
    assert r.status_code == 200
    return {"X-CSRF-Token": r.json()["csrf_token"]}


async def test_admin_creates_and_lists_child(client, admin_user):
    headers = await _admin_client(client, admin_user)

    created = await client.post(
        "/api/v1/children",
        json={
            "username": "charlie",
            "display_name": "Charlie",
            "role": "child",
            "email": "charlie@example.com",
        },
        headers=headers,
    )
    assert created.status_code == 201
    child_id = created.json()["id"]

    listing = await client.get("/api/v1/children")
    assert listing.status_code == 200
    assert [c["username"] for c in listing.json()] == ["Charlie".lower()]

    assert listing.json()[0]["email"] == "charlie@example.com"

    # Soft deactivate.
    dl = await client.delete(f"/api/v1/children/{child_id}", headers=headers)
    assert dl.status_code == 204
    got = await client.get(f"/api/v1/children/{child_id}")
    assert got.json()["is_active"] is False


async def test_create_omits_role_and_is_audited(client, admin_user, db_session):
    headers = await _admin_client(client, admin_user)
    r = await client.post(
        "/api/v1/children",
        json={"username": "dora", "display_name": "Dora", "email": "dora@example.com"},
        headers=headers,
    )
    assert r.status_code == 201, r.text  # role defaults to child

    n = (
        await db_session.execute(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "child.create")
        )
    ).scalar_one()
    assert n == 1


async def test_changing_the_email_revokes_the_childs_sessions(client, admin_user):
    headers = await _admin_client(client, admin_user)
    child_id = (
        await client.post(
            "/api/v1/children",
            json={"username": "dora", "display_name": "Dora", "email": "dora@example.com"},
            headers=headers,
        )
    ).json()["id"]

    client.cookies.clear()
    assert (await sign_in(client, "dora@example.com")).status_code == 200
    child_cookie = client.cookies.get(SESSION_COOKIE)
    assert (await client.get("/api/v1/auth/me")).status_code == 200

    headers = await _admin_client(client, admin_user)
    rp = await client.patch(
        f"/api/v1/children/{child_id}",
        json={"email": "dora.new@example.com"},
        headers=headers,
    )
    assert rp.status_code == 200

    # The old address's session must be dead, or the identity change bought nothing.
    client.cookies.clear()
    client.cookies.set(SESSION_COOKIE, child_cookie)
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_duplicate_email_is_rejected(client, admin_user):
    headers = await _admin_client(client, admin_user)
    body = {"username": "dora", "display_name": "Dora", "email": "dora@example.com"}
    assert (await client.post("/api/v1/children", json=body, headers=headers)).status_code == 201
    body = {"username": "dora2", "display_name": "Dora Two", "email": "DORA@example.com"}
    dupe = await client.post("/api/v1/children", json=body, headers=headers)
    assert dupe.status_code == 409


async def test_deactivate_blocks_login_and_is_audited(client, admin_user, db_session):
    headers = await _admin_client(client, admin_user)
    child_id = (
        await client.post(
            "/api/v1/children",
            json={"username": "dora", "display_name": "Dora", "email": "dora@example.com"},
            headers=headers,
        )
    ).json()["id"]

    assert (await client.delete(f"/api/v1/children/{child_id}", headers=headers)).status_code == 204

    client.cookies.clear()
    # A deactivated kid is not a household member any more, whatever Google says.
    blocked = await sign_in(client, "dora@example.com")
    assert blocked.status_code == 403

    n = (
        await db_session.execute(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "child.deactivate")
        )
    ).scalar_one()
    assert n == 1


async def test_child_cannot_list_children(client, child_user):
    await sign_in(client, "alice@example.com")
    r = await client.get("/api/v1/children")
    assert r.status_code == 403


async def test_mutation_without_csrf_is_forbidden(client, admin_user):
    await sign_in(client, "parent@example.com")
    r = await client.post(
        "/api/v1/children",
        json={
            "username": "nope",
            "display_name": "Nope",
            "role": "child",
        },
    )
    assert r.status_code == 403
