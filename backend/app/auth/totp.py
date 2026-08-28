"""TOTP second factor for admin accounts (spec §12.1)."""

from __future__ import annotations

import pyotp

ISSUER = "ChoreKeeper"


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=ISSUER)


def verify_code(secret: str, code: str) -> bool:
    if not code or not code.strip().isdigit():
        return False
    # valid_window=1 tolerates a +/- 30s clock skew.
    return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)
