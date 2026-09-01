"""Draw the keyed-label plate for #234 into ``propresenter/assets/``.

    .venv/bin/python scripts/make_keyed_art.py

The plate is generated rather than sourced, so its palette is exactly the deck's (``styles.NAVY``
/ ``styles.ACCENT``) and there is no licence question — unlike the stock watercolour Keynote
carries. Its hard edges also key more cleanly than a soft-alpha stroke (#192).

The look is the contemporary broadcast lower-third idiom, chosen in the #234 bake-off over flat
fills, gradient capsules, fading scrims, bare shadowed type and three repainted brush strokes:
a skewed navy-gradient bar with a gold rule along its bottom edge. Re-run this after changing the
palette; ProPresenter reads the PNG at build time, so the deck picks the new art up on the next
build with no code change.
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "src/worship_deck/propresenter/assets"

W, H = 1780, 400          # ~4.45:1, the keyed-label aspect measured off the approved deck
SS = 2                    # supersample, so the slanted ends land clean
NAVY = (0x10, 0x20, 0x3B)
DEEP = (0x1C, 0x33, 0x5E)
GOLD = (0xFF, 0xD4, 0x47)
SKEW = 0.16               # horizontal run of the slanted ends, as a fraction of height


def _mask(draw_fn):
    m = Image.new("L", (W * SS, H * SS), 0)
    draw_fn(ImageDraw.Draw(m), SS)
    return m.resize((W, H), Image.LANCZOS)


def _grad(c0, c1):
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for i in range(W):
        t = i / (W - 1)
        d.line([(i, 0), (i, H)], fill=tuple(round(a + (b - a) * t) for a, b in zip(c0, c1)))
    return img


def _para(d, s, x0, x1, y0, y1):
    """A parallelogram: the top edge shifted right of the bottom edge by SKEW."""
    run = (y1 - y0) * SKEW
    d.polygon([(x0 + run, y0), (x1 + run, y0), (x1, y1), (x0, y1)], fill=255)


def angled_bar() -> Path:
    body = _mask(lambda d, s: _para(d, s, 40 * s, (W - 40) * s, 0, (H - 26) * s))
    rule = _mask(lambda d, s: _para(d, s, 40 * s, (W - 40) * s, (H - 22) * s, (H - 8) * s))
    rgb = Image.composite(Image.new("RGB", (W, H), GOLD), _grad(NAVY, DEEP), rule)
    alpha = Image.composite(rule, Image.eval(body, lambda v: int(v * 0.93)), rule)
    path = OUT / "m1-angled-bar.png"
    Image.merge("RGBA", (*rgb.split(), alpha)).save(path, optimize=True)
    return path


if __name__ == "__main__":
    print(f"Wrote {angled_bar()}")
