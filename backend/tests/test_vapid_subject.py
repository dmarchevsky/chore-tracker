"""The VAPID `sub` claim (spec §4.5).

Push services validate `sub` and refuse the request outright when it is not a real contact
URI. Nothing downstream can recover from that, and the error they return — "Missing 'sub'
from claims" — points at the wrong thing, so it is worth pinning here rather than finding
out from a phone. The check is py_vapid's own, not a second opinion about what is valid.
"""

from __future__ import annotations

import base64
import json

import pytest
from py_vapid import _check_sub

from app.config import get_settings
from app.services.notifications import vapid_subject


@pytest.fixture(autouse=True)
def _clear_settings_cache(monkeypatch):
    monkeypatch.delenv("VAPID_SUBJECT", raising=False)
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _subject(monkeypatch, **env) -> str:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    return vapid_subject()


def test_derives_a_mailto_from_the_hostname_not_the_whole_url(monkeypatch):
    # The bug this replaces: f"mailto:admin@{public_base_url}" produced
    # "mailto:admin@https://chores.example.net", which py_vapid rejects.
    got = _subject(monkeypatch, PUBLIC_BASE_URL="https://chores.example.net")

    assert got == "mailto:admin@chores.example.net"
    assert _check_sub(got)


def test_the_derived_default_survives_a_port_and_a_bare_host(monkeypatch):
    got = _subject(monkeypatch, PUBLIC_BASE_URL="http://localhost:8088")

    assert got == "mailto:admin@localhost"
    assert _check_sub(got)


def test_a_bare_address_in_the_env_file_becomes_a_mailto(monkeypatch):
    # What someone actually types into env.production.
    got = _subject(monkeypatch, VAPID_SUBJECT="parent@example.com")

    assert got == "mailto:parent@example.com"
    assert _check_sub(got)


def test_an_explicit_mailto_is_left_alone(monkeypatch):
    got = _subject(monkeypatch, VAPID_SUBJECT=" mailto:parent@example.com ")

    assert got == "mailto:parent@example.com"
    assert _check_sub(got)


def test_an_https_contact_url_is_left_alone(monkeypatch):
    # The spec allows an https URL instead of a mailto; don't mangle it into one.
    got = _subject(monkeypatch, VAPID_SUBJECT="https://example.com/contact")

    assert got == "https://example.com/contact"


def test_the_configured_subject_wins_over_the_derived_one(monkeypatch):
    got = _subject(
        monkeypatch,
        PUBLIC_BASE_URL="https://chores.example.net",
        VAPID_SUBJECT="parent@example.com",
    )

    assert got == "mailto:parent@example.com"


def test_the_claims_we_build_actually_sign(monkeypatch):
    """End-to-end through py_vapid's signer, which is what pywebpush calls.

    `_check_sub` above is one rule; this is the whole gate a push service puts in front of
    every send, including the `aud` and `exp` handling we leave to defaults. No network:
    signing is local.
    """
    from py_vapid import Vapid01

    from app.vapid_keys import generate

    _, private = generate()
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://chores.example.net")
    get_settings.cache_clear()

    headers = Vapid01.from_string(private).sign(
        {"sub": vapid_subject(), "aud": "https://push.example.com"}
    )

    # It signed at all, which is the point — the malformed sub raised VapidException here.
    # Read the claim back out of the JWT rather than trusting the call not to rewrite it.
    token = headers["Authorization"].split()[1].split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    assert claims["sub"] == "mailto:admin@chores.example.net"
