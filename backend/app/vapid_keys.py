"""Print a fresh VAPID keypair for Web Push (spec §4.5).

Writes nothing: it prints two ``KEY=value`` lines to paste into ``.env`` or
``env.production``, because the keys belong to whoever runs the stack and a generator that
silently rewrote an env file could invalidate every existing subscription in the household.

Run:  just vapid-keys
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _b64(raw: bytes) -> str:
    # Web Push keys are unpadded base64url everywhere — the browser's
    # applicationServerKey, the VAPID header, and pywebpush's private key argument.
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def generate() -> tuple[str, str]:
    """(public, private) as unpadded base64url: an uncompressed P-256 point and its scalar."""
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    private = key.private_numbers().private_value.to_bytes(32, "big")
    return _b64(public), _b64(private)


def main() -> None:
    public, private = generate()
    print(f"VAPID_PUBLIC_KEY={public}")
    print(f"VAPID_PRIVATE_KEY={private}")
    print()
    print("Paste both into .env (dev) or env.production, then restart api + worker.")
    print("Rotating them invalidates every existing subscription — everyone re-subscribes.")


if __name__ == "__main__":
    main()
