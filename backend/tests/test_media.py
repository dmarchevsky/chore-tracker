"""Phase 3: image ingest pipeline + signed media URLs (spec §7.1, §10)."""

from __future__ import annotations

import io
import re
import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from PIL import Image

from app.services import media as media_svc
from app.services.media import (
    MediaError,
    hamming,
    ingest_photo,
    read_media,
    sign_media,
    verify_media_sig,
)


@pytest.fixture
def media_root(tmp_path, monkeypatch):
    monkeypatch.setattr(media_svc, "_media_root", lambda: tmp_path)
    return tmp_path


def _jpeg(w: int, h: int, color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def test_ingest_downscales_and_reencodes(media_root):
    res = ingest_photo(_jpeg(3000, 2000), household_id="hh1")

    assert max(res.width, res.height) == 1568
    assert res.height == round(2000 * 1568 / 3000)
    assert re.fullmatch(r"[0-9a-f]{64}", res.sha256)
    assert re.fullmatch(r"[0-9a-f]{16}", res.phash)
    assert re.fullmatch(
        rf"hh1/\d{{4}}/\d{{2}}/{res.sha256[:2]}/{res.sha256}\.jpg", res.storage_path
    )

    on_disk = media_root / res.storage_path
    assert on_disk.is_file() and on_disk.stat().st_size == res.bytes


def test_ingest_is_deterministic_and_content_addressed(media_root):
    a = ingest_photo(_jpeg(800, 600), household_id="hh1")
    b = ingest_photo(_jpeg(800, 600), household_id="hh1")
    assert a.sha256 == b.sha256 and a.storage_path == b.storage_path


def test_phash_distinguishes_different_images(media_root):
    red = ingest_photo(_jpeg(400, 400, (220, 20, 20)), household_id="hh1")
    split = Image.new("RGB", (400, 400), (10, 10, 10))
    for x in range(200):
        for y in range(400):
            split.putpixel((x, y), (240, 240, 240))
    buf = io.BytesIO()
    split.save(buf, format="JPEG", quality=95)
    other = ingest_photo(buf.getvalue(), household_id="hh1")

    assert hamming(red.phash, other.phash) > 8


def test_ingest_rejects_garbage(media_root):
    with pytest.raises(MediaError):
        ingest_photo(b"not an image", household_id="hh1")


def test_read_media_blocks_path_traversal(media_root):
    with pytest.raises(MediaError):
        read_media("../../etc/passwd")
    with pytest.raises(MediaError):
        read_media("hh1/2025/01/ab/missing.jpg")


def test_sign_and_verify_media_url():
    sid = str(uuid.uuid4())
    url = sign_media(sid, 1, ttl_s=300)
    q = parse_qs(urlparse(url).query)
    assert verify_media_sig(sid, 1, q["exp"][0], q["sig"][0])
    # Tampered signature and wrong index both fail.
    assert not verify_media_sig(sid, 1, q["exp"][0], "deadbeef")
    assert not verify_media_sig(sid, 2, q["exp"][0], q["sig"][0])


def test_expired_signature_is_rejected():
    sid = str(uuid.uuid4())
    url = sign_media(sid, 0, ttl_s=-5)
    q = parse_qs(urlparse(url).query)
    assert not verify_media_sig(sid, 0, q["exp"][0], q["sig"][0])
