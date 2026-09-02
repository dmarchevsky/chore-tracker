"""The rate-limit maps are keyed by attacker-supplied input on unauthenticated paths.

`/api/v1/checkin/{token}` is the one path Cloudflare Access bypasses by policy, and its
key is the path segment, so anything remembered here is remembered on someone else's say-so
(spec §6.2, §12.1). These pin the two properties that follow from that: the maps stay
bounded, and the login backoff still escalates across attempts.
"""

from __future__ import annotations

import pytest

from app.auth import ratelimit
from app.auth.ratelimit import (
    _ACCOUNT_TTL_S,
    _MAX_KEYS,
    _TOKEN_WINDOW_S,
    account_locked_for,
    ip_allowed,
    record_failure,
    record_success,
    token_allowed,
)


@pytest.fixture(autouse=True)
def _clean():
    ratelimit.reset()
    yield
    ratelimit.reset()


def test_expired_token_keys_are_swept():
    """A guessed token is never seen again. Without a sweep every guess is remembered
    forever, which is an unauthenticated memory leak with a public path in front of it."""
    for i in range(50):
        token_allowed(f"guess-{i}", now=1000.0)
    assert len(ratelimit._token_hits) == 50

    # An hour later, one live caller — the stale 50 go with it.
    token_allowed("real-token", now=1000.0 + _TOKEN_WINDOW_S + 1)
    assert set(ratelimit._token_hits) == {"real-token"}


def test_token_map_never_exceeds_the_cap_even_when_every_key_is_live():
    for i in range(_MAX_KEYS + 500):
        token_allowed(f"spray-{i}", now=1000.0)
    assert len(ratelimit._token_hits) <= _MAX_KEYS


def test_ip_map_is_bounded_too():
    for i in range(_MAX_KEYS + 100):
        ip_allowed(f"10.0.{i // 256}.{i % 256}", now=1000.0)
    assert len(ratelimit._ip_hits) <= _MAX_KEYS


def test_reading_a_lock_does_not_remember_the_username():
    """A login flood with invented usernames grew this map one attempt at a time."""
    for i in range(100):
        assert account_locked_for(f"nobody-{i}", now=1000.0) == 0.0
    assert ratelimit._accounts == {}


def test_backoff_escalates_across_attempts():
    """The lock lapsing must not erase the count — otherwise a guesser resets their own
    backoff simply by waiting each one out, and it never grows past the first step."""
    now = 1000.0
    for _ in range(4):
        record_failure("parent", now=now)
        now += account_locked_for("parent", now=now) + 1

    record_failure("parent", now=now)
    assert account_locked_for("parent", now=now) >= 4


def test_a_quiet_account_is_eventually_forgotten():
    record_failure("parent", now=1000.0)
    record_failure("someone-else", now=1000.0 + _ACCOUNT_TTL_S + 1)
    assert "parent" not in ratelimit._accounts


def test_success_clears_the_backoff():
    record_failure("parent", now=1000.0)
    record_failure("parent", now=1001.0)
    record_failure("parent", now=1002.0)
    assert account_locked_for("parent", now=1002.0) > 0

    record_success("parent")
    assert account_locked_for("parent", now=1002.0) == 0.0
