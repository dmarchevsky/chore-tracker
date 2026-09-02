"""Login + webhook rate limiting (spec §6.2, §12.1): 10/min/IP and per-account backoff.

Counters are in-process and deliberately stay that way: one `api` replica serves every
request (the worker never handles HTTP), so a shared store would buy nothing but a
round-trip. The cost is that a restart forgives outstanding backoff, which is acceptable
for a household app and is why the durable defences — Cloudflare Access, the WAF rule on
`/checkin/`, and the token's own entropy — are the ones that matter.

**Every map here is keyed by attacker-controlled input** and reached without a session:
`_token_hits` by the path segment of `/api/v1/checkin/{token}`, which Cloudflare Access
bypasses by design. So each map is swept and hard-capped; an unbounded `defaultdict` let
anyone on the internet grow this process until it was killed.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

_IP_WINDOW_S = 60
_IP_MAX = 10

_TOKEN_WINDOW_S = 3600
_TOKEN_MAX = 20  # spec §6.2

# How long a quiet account is remembered. Longer than the 5-minute backoff ceiling, so
# escalation survives the gap between attempts and a patient guesser cannot reset their
# own counter simply by waiting out each lock.
_ACCOUNT_TTL_S = 3600

# Hard ceiling per map, far above a household's real traffic (a few devices, a handful of
# tokens). Reaching it means someone is spraying; the sweep below runs first and only a
# flood of *live* keys can still hit it.
_MAX_KEYS = 4096


@dataclass
class _AccountState:
    failures: int = 0
    locked_until: float = 0.0
    last_failure_at: float = field(default=0.0)


_ip_hits: dict[str, deque[float]] = {}
_accounts: dict[str, _AccountState] = {}
_token_hits: dict[str, deque[float]] = {}


def _sweep(bucket: dict[str, deque[float]], *, window_s: int, now: float) -> None:
    """Drop keys whose window has fully expired — the one-shot callers and the guessed
    tokens that will never be seen again, which is what actually accumulates."""
    for key in [k for k, hits in bucket.items() if not hits or now - hits[-1] > window_s]:
        del bucket[key]


def _allowed(
    bucket: dict[str, deque[float]], key: str, *, window_s: int, limit: int, now: float
) -> bool:
    if key not in bucket:
        _sweep(bucket, window_s=window_s, now=now)
        if len(bucket) >= _MAX_KEYS:
            # Every remaining key is live, so there is nothing selective left to drop.
            # Forgiving one window beats growing without bound.
            bucket.clear()
    hits = bucket.setdefault(key, deque())
    while hits and now - hits[0] > window_s:
        hits.popleft()
    if len(hits) >= limit:
        return False
    hits.append(now)
    return True


def token_allowed(token: str, *, now: float | None = None) -> bool:
    """20 check-in webhook calls per hour per token (spec §6.2)."""
    now = now if now is not None else time.monotonic()
    return _allowed(_token_hits, token, window_s=_TOKEN_WINDOW_S, limit=_TOKEN_MAX, now=now)


def ip_allowed(ip: str, *, now: float | None = None) -> bool:
    now = now if now is not None else time.monotonic()
    return _allowed(_ip_hits, ip, window_s=_IP_WINDOW_S, limit=_IP_MAX, now=now)


def account_locked_for(username: str, *, now: float | None = None) -> float:
    """Seconds of backoff left. A pure read: an unknown username is never recorded, which
    is what let a flood of invented usernames grow this map one login attempt at a time."""
    now = now if now is not None else time.monotonic()
    st = _accounts.get(username)
    return max(0.0, st.locked_until - now) if st is not None else 0.0


def record_failure(username: str, *, now: float | None = None) -> None:
    now = now if now is not None else time.monotonic()
    if username not in _accounts:
        for key in [k for k, st in _accounts.items() if now - st.last_failure_at > _ACCOUNT_TTL_S]:
            del _accounts[key]
        if len(_accounts) >= _MAX_KEYS:
            _accounts.clear()
    st = _accounts.setdefault(username, _AccountState())
    st.failures += 1
    st.last_failure_at = now
    # 0,0,2,4,8,16,... seconds, capped at 5 minutes.
    backoff = 0 if st.failures <= 2 else min(2 ** (st.failures - 2), 300)
    st.locked_until = now + backoff


def record_success(username: str) -> None:
    _accounts.pop(username, None)


def reset() -> None:
    """Test helper."""
    _ip_hits.clear()
    _accounts.clear()
    _token_hits.clear()
