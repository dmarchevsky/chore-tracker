"""Phase 1: admin CRUD over child accounts; children cannot reach admin endpoints."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _admin_client(client, admin_user, totp_now):
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "parent", "password": "parent-pass", "totp_code": totp_now()},
    )
    assert r.status_code == 200
    return {"X-CSRF-Token": r.json()["csrf_token"]}


async def test_admin_creates_and_lists_child(client, admin_user, totp_now):
    headers = await _admin_client(client, admin_user, totp_now)

    created = await client.post(
        "/api/v1/children",
        json={
            "username": "charlie",
            "display_name": "Charlie",
            "role": "child",
            "password": "charlie-pass",
        },
        headers=headers,
    )
    assert created.status_code == 201
    child_id = created.json()["id"]

    listing = await client.get("/api/v1/children")
    assert listing.status_code == 200
    assert [c["username"] for c in listing.json()] == ["Charlie".lower()]

    # Password reset + soft deactivate.
    rp = await client.post(
        f"/api/v1/children/{child_id}/password-reset",
        json={"new_password": "new-charlie-pass"},
        headers=headers,
    )
    assert rp.status_code == 204

    dl = await client.delete(f"/api/v1/children/{child_id}", headers=headers)
    assert dl.status_code == 204
    got = await client.get(f"/api/v1/children/{child_id}")
    assert got.json()["is_active"] is False


async def test_child_cannot_list_children(client, child_user):
    await client.post("/api/v1/auth/login", json={"username": "alice", "password": "alice-pass"})
    r = await client.get("/api/v1/children")
    assert r.status_code == 403


async def test_mutation_without_csrf_is_forbidden(client, admin_user, totp_now):
    await client.post(
        "/api/v1/auth/login",
        json={"username": "parent", "password": "parent-pass", "totp_code": totp_now()},
    )
    r = await client.post(
        "/api/v1/children",
        json={
            "username": "nope",
            "display_name": "Nope",
            "role": "child",
            "password": "nope-pass",
        },
    )
    assert r.status_code == 403
