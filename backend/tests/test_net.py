"""Proxy-aware client IP derivation (spec §12.2)."""

from __future__ import annotations

from starlette.requests import Request

from app.config import Settings
from app.net import client_ip


def _req(headers: dict[str, str], peer: str = "10.0.0.9") -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "client": (peer, 12345)})


def _settings(trust: bool) -> Settings:
    return Settings(TRUST_PROXY_HEADERS="true" if trust else "false")


def test_ignores_forwarded_headers_by_default():
    r = _req({"CF-Connecting-IP": "203.0.113.7", "X-Forwarded-For": "203.0.113.7"})
    assert client_ip(r, _settings(trust=False)) == "10.0.0.9"


def test_prefers_cf_connecting_ip_when_trusted():
    r = _req({"CF-Connecting-IP": "203.0.113.7", "X-Forwarded-For": "9.9.9.9, 10.0.0.1"})
    assert client_ip(r, _settings(trust=True)) == "203.0.113.7"


def test_falls_back_to_xff_first_hop_when_trusted():
    r = _req({"X-Forwarded-For": "203.0.113.7, 10.0.0.1"})
    assert client_ip(r, _settings(trust=True)) == "203.0.113.7"


def test_falls_back_to_peer_when_no_headers():
    assert client_ip(_req({}), _settings(trust=True)) == "10.0.0.9"
