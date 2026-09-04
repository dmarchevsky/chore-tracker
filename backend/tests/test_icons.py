"""The generated app icons (scripts/icons.py).

These assets live under frontend/public but are drawn by a Python script, and this is the
repo's only Python test runner — so the generator and its output are checked here, next to
each other, rather than from vitest (which would need node type packages to read a file).
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import struct
import zlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "frontend" / "public"

_spec = importlib.util.spec_from_file_location("icons", ROOT / "scripts" / "icons.py")
assert _spec and _spec.loader
icons = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(icons)

SIZES = {
    "icon-192.png": 192,
    "icon-512.png": 512,
    "icon-512-maskable.png": 512,
    "apple-touch-icon.png": 180,
}


def _chunks(data: bytes):
    """Yield (type, crc_stored, crc_computed) for every chunk in a PNG."""
    i = 8  # past the signature
    while i < len(data):
        length = struct.unpack(">I", data[i : i + 4])[0]
        typ = data[i + 4 : i + 8].decode("latin1")
        stored = struct.unpack(">I", data[i + 8 + length : i + 12 + length])[0]
        yield typ, stored, zlib.crc32(data[i + 4 : i + 8 + length])
        i += 12 + length
        if typ == "IEND":
            break


@pytest.mark.parametrize("name,size", SIZES.items())
def test_icon_is_a_square_of_the_declared_size(name, size):
    from PIL import Image

    with Image.open(PUBLIC / name) as im:
        assert im.size == (size, size)


@pytest.mark.parametrize("name", SIZES)
def test_icon_chunk_crcs_are_valid(name):
    """The icons that shipped from phase 5 to phase 8 had every CRC zeroed.

    Browsers do not verify them, so the files rendered and nothing ever complained — but
    Pillow refused to open them outright, and a regression would look identical.
    """
    for typ, stored, computed in _chunks((PUBLIC / name).read_bytes()):
        assert stored == computed, f"{name}: {typ} CRC {stored:08x} != {computed:08x}"


def test_maskable_tile_is_not_the_rounded_one():
    """Same artwork, different background: full-bleed for the OS to mask, rounded otherwise.

    Pointing the manifest's maskable entry back at the rounded file is the easy mistake.
    """
    assert (PUBLIC / "icon-512-maskable.png").read_bytes() != (PUBLIC / "icon-512.png").read_bytes()


def test_rounded_tile_has_transparent_corners_and_the_square_one_does_not():
    assert icons.render(64).getpixel((0, 0))[3] == 0
    assert icons.render(64, square=True).getpixel((0, 0)) == icons.NAVY


def test_the_check_is_drawn_in_the_tile_colour_over_the_coin():
    """Contrast is the whole reason the check is navy rather than emerald: navy on amber is
    9.6:1 and survives a 16px tab, emerald on amber is 1.4:1 and does not."""
    im = icons.render(512, square=True)
    # A point on the long arm of the check, and one on the coin clear of it.
    assert im.getpixel((round(0.60 * 512), round(0.455 * 512))) == icons.NAVY
    assert im.getpixel((round(0.50 * 512), round(0.27 * 512))) == icons.AMBER


def test_index_html_icon_links_all_resolve():
    html = (ROOT / "frontend" / "index.html").read_text()
    hrefs = re.findall(r'<link rel="(?:icon|apple-touch-icon)"[^>]*href="([^"]+)"', html)
    assert hrefs
    for href in hrefs:
        assert (PUBLIC / href.lstrip("/")).exists(), href
