"""Login rate limiting (spec §12.1): 10/min/IP + per-account exponential backoff.

Phase 1 keeps counters in-process. Phase 6 moves these to Postgres-backed counters so
limits hold across the api + worker replicas.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass

_IP_WINDOW_S = 60
_IP_MAX = 10


@dataclass
class _AccountState:
    failures: int = 0
    locked_until: float = 0.0


_ip_hits: dict[str, deque[float]] = defaultdict(deque)
_accounts: dict[str, _AccountState] = defaultdict(_AccountState)
_token_hits: dict[str, deque[float]] = defaultdict(deque)

_TOKEN_WINDOW_S = 3600
_TOKEN_MAX = 20  # spec §6.2


def token_allowed(token: str, *, now: float | None = None) -> bool:
    """20 check-in webhook calls per hour per token (spec §6.2)."""
    now = now if now is not None else time.monotonic()
    hits = _token_hits[token]
    while hits and now - hits[0] > _TOKEN_WINDOW_S:
        hits.popleft()
    if len(hits) >= _TOKEN_MAX:
        return False
    hits.append(now)
    return True


def ip_allowed(ip: str, *, now: float | None = None) -> bool:
    now = now if now is not None else time.monotonic()
    hits = _ip_hits[ip]
    while hits and now - hits[0] > _IP_WINDOW_S:
        hits.popleft()
    if len(hits) >= _IP_MAX:
        return False
    hits.append(now)
    return True


def account_locked_for(username: str, *, now: float | None = None) -> float:
    now = now if now is not None else time.monotonic()
    st = _accounts[username]
    return max(0.0, st.locked_until - now)


def record_failure(username: str, *, now: float | None = None) -> None:
    now = now if now is not None else time.monotonic()
    st = _accounts[username]
    st.failures += 1
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
