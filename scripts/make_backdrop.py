"""Bake the 네이비 프레임 blur backdrops into ``propresenter/assets/backdrops/`` (#224).

    .venv/bin/python scripts/make_backdrop.py            # the shipped strength
    .venv/bin/python scripts/make_backdrop.py --all      # every strength, for #241

ProPresenter cannot blur a background itself: ``Fill.backgroundEffect.backgroundBlur`` renders as
an unrendered placeholder in 21.4 and **crashes** when the slide is selected (see
``propresenter/elements.py``). So the blur is baked here, offline, and ``styles._framed`` places
the result as an ordinary full-bleed image. Baking also keeps Pillow a *dev* dependency — the
runtime pipeline never touches it — and makes the deck byte-identical build to build.

What is baked is exactly ``scripts/render_style_samples.py``'s Option 3 backdrop CSS
(``filter: blur() brightness() saturate(.75)``) **minus the navy tint**: ``_framed`` already
draws the tint live as ``styles.TINT_RGBA``, so baking it too would tint twice.

Strengths. #189 specified only ``soft``; a 3×3 trial against the three sources showed every one
of them collapsing into the same flat navy there — the photo stops contributing at all, so the
looser looks exist to give #241's sample sheet something to compare. ``open`` is the shipped
pick (2026-09-03): ``soft``'s darkness with the blur pulled back so the building actually reads.
Dropping blur 26 -> 16 leaves the histogram alone — brightness and tint fix the extremes — but
lifts local edge energy ~20%, which is the part the eye sees.

Only ``SHIPPED`` is committed; ``--all`` re-renders the rest locally for #241 and #225.

Sources (committed alongside the bakes so any strength can be re-rendered later):

``church-exterior.jpg``
    The church building at golden hour — a copy of ``assets/pre-service-church.jpg``, which also
    ships as an opening pre-service plate (``styles.PRE_SERVICE_IMAGES``). Kept as a separate
    file so re-cropping one never silently changes the other.
``congregation.jpg``
    The 2025-11 all-church-members photo from the church home page
    (``npcwheeling.com/wp-content/uploads/2025/12/All-church-members-2025-NOV.jpg``). #224 as
    filed argued against congregation photos on privacy grounds; the church overruled that for
    this use (2026-09-03) — see the issue. 2500×803, so aspect-fill drops ~43% of the width.
``sanctuary-cc0.jpg``
    A dark church interior, Unsplash photo ``JRsZWmRd_Ws``. Unsplash License, free for commercial
    use, no attribution required — the same licence bar as the stock texture behind ``BRUSH``.
"""
import argparse
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter

ASSETS = Path(__file__).resolve().parent.parent / "src/worship_deck/propresenter/assets/backdrops"

W, H = 1920, 1080
SATURATE = 0.75   # from the sample CSS; easy to miss next to the blur/brightness pair

# name -> (blur radius, brightness, navy-tint alpha). All three move together: the tint is drawn
# live by `styles._framed` rather than baked, so `styles.BACKDROPS` carries the alpha alongside
# the image and `test_the_bake_strengths_and_the_shipped_tint_agree` pins the two files together.
# Tint is by far the strongest of the three — it alone decides how much photo survives — so a
# strength that varied blur and brightness but not tint would not be a distinct look at all.
STRENGTHS = {
    "soft": (26, 0.32, 0.62),   # #189 as specified — the photo reads as flat navy
    "open": (16, 0.32, 0.62),   # SHIPPED: soft's darkness, less blur so the building reads
    "mid": (20, 0.55, 0.45),    # the source is clearly legible as atmosphere
    "light": (14, 0.70, 0.32),  # photographic, but bright areas start to fight white text
}
SHIPPED = "open"
SOURCES = ("church-exterior", "congregation", "sanctuary-cc0")


def bake(src: Path, blur: float, brightness: float, tint: float = 0.0) -> Image.Image:
    """Aspect-fill ``src`` to the 1920×1080 canvas, then blur/darken/desaturate it."""
    im = Image.open(src).convert("RGB")
    scale = max(W / im.width, H / im.height)
    im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
    left, top = (im.width - W) // 2, (im.height - H) // 2
    im = im.crop((left, top, left + W, top + H))
    im = im.filter(ImageFilter.GaussianBlur(blur))
    im = ImageEnhance.Color(im).enhance(SATURATE)
    # `tint` is accepted but deliberately unused: it belongs to the look, not to the file, and
    # `styles._framed` draws it as a live shape over the image. Baking it would tint twice.
    return im.point(lambda v: round(v * brightness))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true", help="every strength, not just the shipped one")
    args = ap.parse_args()

    # PNG, not JPEG: a blurred dark frame is nothing but smooth gradient, which is exactly where
    # JPEG bands — and banding is the one artefact a 26px blur cannot hide.
    for name in SOURCES:
        for key in STRENGTHS if args.all else [SHIPPED]:
            out = ASSETS / f"{name}-{key}.png"
            bake(ASSETS / f"{name}.jpg", *STRENGTHS[key]).save(out)
            print(f"{out.relative_to(ASSETS.parents[4])}  {out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
