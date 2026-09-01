"""Shared test helpers."""

from __future__ import annotations

from unittest.mock import patch

from httpx import AsyncClient, Response

from app.api.v1 import auth as auth_router


async def sign_in(client: AsyncClient, email: str) -> Response:
    """Sign in the way everyone does in production: Cloudflare Access vouches for a
    Google address and ``/auth/me`` turns it into a session (spec §12.1).

    The Access middleware is only installed when ``CF_ACCESS_*`` is configured, which it
    is not under test, so the verified-claims lookup is stubbed for the one call. The
    response is returned as-is, so callers read ``csrf_token`` from it exactly as they
    did when this was a password POST.
    """
    with patch.object(auth_router, "access_email", lambda request: email):
        return await client.get("/api/v1/auth/me")
