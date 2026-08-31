"""Request-origin helpers for a proxied deployment (spec §12.2).

Behind the Cloudflare Tunnel every request's peer is the ``proxy`` container, so
``request.client.host`` is useless for rate limiting and audit. Cloudflare puts the real
client IP in ``CF-Connecting-IP``; the reverse proxy forwards ``X-Forwarded-For``. We only
believe those headers when ``TRUST_PROXY_HEADERS`` is set — on the LAN they are spoofable.
"""

from __future__ import annotations

from starlette.requests import Request

from app.config import Settings, get_settings


def client_ip(request: Request, settings: Settings | None = None) -> str:
    s = settings or get_settings()
    if s.trust_proxy_headers:
        cf = request.headers.get("cf-connecting-ip")
        if cf:
            return cf.strip()
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
