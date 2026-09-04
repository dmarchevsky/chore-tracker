"""Draw the ChoreKeeper app icon — a checkmark over a coin — at every size the app asks for.

Run through the backend's environment (`just icons`), which is where Pillow already lives;
nothing here is imported by the app itself.

    icons.py [dest]        default dest: frontend/public

Geometry is expressed as fractions of the canvas so one scale factor covers 16px and 512px
alike, and every shape is drawn at SUPERSAMPLE times the final size and then reduced —
Pillow's primitives are hard-aliased, and a raw 16px draw is a staircase.
"""

from __future__ import annotations

import pathlib
import sys

from PIL import Image, ImageDraw

# Palette tokens, straight from frontend/src/index.css.
NAVY = (15, 23, 42)  # --slate-900, the manifest's theme_color
AMBER = (251, 191, 36)  # --amber-400, the coin face
AMBER_RIM = (217, 119, 6)  # --amber-600

# Fractions of the canvas.
CORNER = 0.22  # tile corner radius; 0 for the maskable variant
COIN = 0.72  # coin diameter — inside the 80% maskable safe zone
RIM = 0.035  # coin rim stroke
CHECK = 0.13  # check stroke; the knob to turn if the tab icon reads as a dot
# The check itself: (x, y) fractions, short arm then long arm.
CHECK_POINTS = ((0.34, 0.51), (0.45, 0.62), (0.67, 0.39))

SUPERSAMPLE = 4

ICO_SIZES = (16, 32, 48)


def render(size: int, *, square: bool = False) -> Image.Image:
    """One square icon.

    ``square`` gives a full-bleed opaque tile, for the two surfaces that do their own
    rounding: a maskable icon is clipped to whatever shape the OS picks, and iOS both
    rounds the apple-touch-icon and composites any alpha against black. Everything else
    gets rounded corners here, which means transparent ones — a tab is not always white.
    """
    s = size * SUPERSAMPLE
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    if square:
        d.rectangle((0, 0, s, s), fill=NAVY)
    else:
        d.rounded_rectangle((0, 0, s - 1, s - 1), radius=CORNER * s, fill=NAVY)

    inset = (1 - COIN) / 2 * s
    d.ellipse(
        (inset, inset, s - inset, s - inset),
        fill=AMBER,
        outline=AMBER_RIM,
        width=max(1, round(RIM * s)),
    )

    # The check is knocked out in the tile's own navy: emerald on amber is a 1.4:1 contrast
    # ratio and merges into one smudge at tab size, where navy on amber is 9.6:1.
    d.line(
        [(x * s, y * s) for x, y in CHECK_POINTS],
        fill=NAVY,
        width=round(CHECK * s),
        joint="curve",
    )
    # `joint="curve"` rounds the elbow but leaves the two ends square; cap them by hand.
    r = CHECK * s / 2
    for x, y in (CHECK_POINTS[0], CHECK_POINTS[-1]):
        d.ellipse((x * s - r, y * s - r, x * s + r, y * s + r), fill=NAVY)

    img = img.resize((size, size), Image.LANCZOS)
    return img.convert("RGB") if square else img


def svg() -> str:
    """The same drawing as vector, for tabs that prefer it. Kept in step with the constants."""
    (x0, y0), (x1, y1), (x2, y2) = CHECK_POINTS
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1">
  <rect width="1" height="1" rx="{CORNER}" fill="rgb{NAVY}"/>
  <circle cx="0.5" cy="0.5" r="{COIN / 2 - RIM / 2}"
          fill="rgb{AMBER}" stroke="rgb{AMBER_RIM}" stroke-width="{RIM}"/>
  <polyline points="{x0},{y0} {x1},{y1} {x2},{y2}"
            fill="none" stroke="rgb{NAVY}" stroke-width="{CHECK}"
            stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""


def main(argv: list[str]) -> None:
    dest = pathlib.Path(argv[0] if argv else "frontend/public")
    dest.mkdir(parents=True, exist_ok=True)

    written = []
    for name, size in (("icon-192.png", 192), ("icon-512.png", 512)):
        render(size).save(dest / name)
        written.append(name)

    for name, size in (("apple-touch-icon.png", 180), ("icon-512-maskable.png", 512)):
        render(size, square=True).save(dest / name)
        written.append(name)

    largest = render(max(ICO_SIZES))
    largest.save(dest / "favicon.ico", sizes=[(n, n) for n in ICO_SIZES])
    written.append("favicon.ico")

    (dest / "favicon.svg").write_text(svg())
    written.append("favicon.svg")

    for name in written:
        print(f"{dest / name} ({(dest / name).stat().st_size} bytes)")


if __name__ == "__main__":
    main(sys.argv[1:])
