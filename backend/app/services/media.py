"""Image ingest pipeline + content-addressed storage + signed media URLs (spec §5, §7.1, §13.1).

Ingest: record EXIF, normalise orientation, downscale to 1568px long edge, re-encode JPEG
q85 (stripping metadata), compute sha256 + pHash, and write to
``{household}/{yyyy}/{mm}/{sha256[:2]}/{sha256}.jpg`` under ``MEDIA_ROOT``. Content-addressed
so dedup is free.

Media is only ever served through the authenticated API (never as static files); URLs are
HMAC-signed with a short TTL so a leaked link expires (spec §10).
"""

from __future__ import annotations

import hashlib
import hmac
import io
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageOps

from app.config import get_settings

MAX_LONG_EDGE = 1568
JPEG_QUALITY = 85
DEFAULT_URL_TTL_S = 300  # 5 minutes (spec §10)

_EXIF_TAGS = {271: "Make", 272: "Model", 306: "DateTime", 36867: "DateTimeOriginal"}


class MediaError(ValueError):
    """Unreadable upload or a path that escapes MEDIA_ROOT."""


@dataclass(frozen=True)
class IngestResult:
    sha256: str
    phash: str
    width: int
    height: int
    bytes: int
    storage_path: str  # relative to MEDIA_ROOT
    exif: dict[str, str]


def _media_root() -> Path:
    return Path(get_settings().media_root)


def _extract_exif(img: Image.Image) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        raw = img.getexif()
    except Exception:  # pragma: no cover - Pillow quirk on odd files
        return out
    for tag_id, name in _EXIF_TAGS.items():
        value = raw.get(tag_id)
        if value:
            out[name] = str(value).strip("\x00 ").strip()
    return out


def _dhash(img: Image.Image, size: int = 8) -> str:
    """Row-wise difference hash — robust to resize/recompress, catches reuse (spec §6.1)."""
    small = img.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    px = small.tobytes()  # one byte per pixel in mode "L", row-major
    bits = 0
    for row in range(size):
        for col in range(size):
            left = px[row * (size + 1) + col]
            right = px[row * (size + 1) + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return f"{bits:016x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def ingest_photo(raw: bytes, *, household_id: str, now: datetime | None = None) -> IngestResult:
    now = now or datetime.now(UTC)
    try:
        src = Image.open(io.BytesIO(raw))
        src.load()
    except Exception as exc:
        raise MediaError(f"unreadable image: {exc}") from exc

    exif = _extract_exif(src)
    img = ImageOps.exif_transpose(src)  # bake rotation in, then we can strip metadata
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    long_edge = max(img.size)
    if long_edge > MAX_LONG_EDGE:
        scale = MAX_LONG_EDGE / long_edge
        img = img.resize(
            (round(img.width * scale), round(img.height * scale)), Image.Resampling.LANCZOS
        )

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    data = buf.getvalue()

    sha = hashlib.sha256(data).hexdigest()
    phash = _dhash(img)
    rel = f"{household_id}/{now:%Y}/{now:%m}/{sha[:2]}/{sha}.jpg"

    dest = _media_root() / rel
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".jpg.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dest)

    return IngestResult(
        sha256=sha,
        phash=phash,
        width=img.width,
        height=img.height,
        bytes=len(data),
        storage_path=rel,
        exif=exif,
    )


def read_media(storage_path: str) -> bytes:
    root = _media_root().resolve()
    full = (root / storage_path).resolve()
    if not full.is_relative_to(root):
        raise MediaError("path escapes MEDIA_ROOT")
    if not full.is_file():
        raise MediaError("media not found")
    return full.read_bytes()


# --- signed URLs ---------------------------------------------------------------


def _sig(payload: str) -> str:
    key = get_settings().session_secret.encode()
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()[:32]


def sign_media(submission_id: str, idx: int, *, ttl_s: int = DEFAULT_URL_TTL_S) -> str:
    exp = int(time.time()) + ttl_s
    payload = f"{submission_id}:{idx}:{exp}"
    return f"/api/v1/submissions/{submission_id}/media/{idx}?exp={exp}&sig={_sig(payload)}"


def verify_media_sig(submission_id: str, idx: int, exp: str | int, sig: str) -> bool:
    try:
        exp_i = int(exp)
    except (TypeError, ValueError):
        return False
    if exp_i < int(time.time()):
        return False
    expected = _sig(f"{submission_id}:{idx}:{exp_i}")
    return hmac.compare_digest(expected, sig or "")
