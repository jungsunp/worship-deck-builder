"""교회소식 photo handling: shrink uploads, and lay photos out as collage slides.

Operators used to paste 6–8 full-size KakaoTalk photos into the deck by hand (+34–40 MB per week
in the 2026-08-16 / 2026-10-04 decks). Photos are now uploaded in the review app, shrunk here at
upload time, and the Keynote build lays them out on collage slides (`keynote.build`).

Pure Python + Pillow, so it runs (and is tested) off-Mac. The only layout rules the operator's
hand-made decks settled are: photo-only slides (no title), photos edge to edge, up to 6 per slide.
"""

from __future__ import annotations

import math
from itertools import combinations, pairwise
from typing import BinaryIO

from PIL import Image, ImageOps

# Long edge of a stored photo. The slide is 1920x1080 and a photo never gets bigger than that.
MAX_EDGE = 1920
JPEG_QUALITY = 80
# From the operator's 10-04 deck (6 photos on one slide); more spill onto a further slide.
MAX_PER_SLIDE = 6

# Smallest photo (px² on the 1920x1080 slide) a collage may contain. Six 4:3 photos in 3+3 rows
# (the operator's 10-04 layout, ~632x474) are 300 k; this keeps four portraits in a row (~297 k)
# but sends five-plus portraits to a second slide, so photos stay large enough for elders.
MIN_PHOTO_AREA = 280_000

SLIDE_W, SLIDE_H = 1920, 1080
GAP = 8  # px between photos and (half of it) around the block; small so photos stay large


def downscale_photo(src: BinaryIO, dest) -> tuple[int, int]:
    """Shrink an uploaded photo to a JPEG (long edge <= MAX_EDGE, q80) at `dest`; return (w, h).

    Bakes in the EXIF orientation (phone photos are often stored sideways with a rotate flag,
    which Keynote may not honour) and drops metadata (GPS etc.). Raises `ValueError` when the
    bytes are not a readable image.
    """
    try:
        img = Image.open(src)
        img.load()
    except Exception as e:  # Pillow raises many types for bad input
        raise ValueError("not a readable image") from e
    img = ImageOps.exif_transpose(img)
    img.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
    img.convert("RGB").save(dest, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return img.size


def _balanced(items: list, slides: int) -> list[list]:
    base, extra = divmod(len(items), slides)
    out, i = [], 0
    for s in range(slides):
        n = base + (1 if s < extra else 0)
        out.append(items[i : i + n])
        i += n
    return out


def chunk_photos(photos: list[dict], per_slide: int = MAX_PER_SLIDE) -> list[list[dict]]:
    """Split photos ({w, h, ...}) across slides: as few as possible, but never tiny photos.

    Starts from the fewest slides that respect `per_slide` and adds slides until every photo on
    every slide is at least MIN_PHOTO_AREA px² in the justified layout — six landscape photos fit
    one slide (3+3 rows), but six portraits would be ~190 k px² each, so they take two. Photos
    stay in order and each slide gets an even share (8 -> 4+4, not 6+2).
    """
    n = len(photos)
    if n == 0:
        return []
    for slides in range(math.ceil(n / per_slide), n + 1):
        chunks = _balanced(photos, slides)
        if all(_smallest_area(c) >= MIN_PHOTO_AREA for c in chunks):
            return chunks
    return _balanced(photos, n)


def _smallest_area(chunk: list[dict]) -> int:
    boxes = collage_layout([(p["w"], p["h"]) for p in chunk])
    return min(w * h for _, _, w, h in boxes)


def collage_layout(
    sizes: list[tuple[int, int]],
    width: int = SLIDE_W,
    height: int = SLIDE_H,
    gap: int = GAP,
) -> list[tuple[int, int, int, int]]:
    """Justified-rows layout: one (x, y, w, h) per photo, in order, aspect ratios preserved.

    Photos are never cropped or overlapped. Every consecutive split of the photos into rows is
    tried; each row is scaled so it spans the full width, and if the rows stack taller than the
    slide the whole block shrinks to fit. The split that leaves the photos largest wins; the
    block is centred on the slide.
    """
    n = len(sizes)
    if n == 0:
        return []
    aspects = [w / h for w, h in sizes]
    inner_w, inner_h = width - gap, height - gap  # half a gap of margin all round

    best: tuple[tuple[float, float], list[list[int]], float] | None = None
    for k in range(n):  # k = number of cut points -> k+1 rows
        for cuts in combinations(range(1, n), k):
            bounds = [0, *cuts, n]
            rows = [list(range(a, b)) for a, b in pairwise(bounds)]
            heights = [(inner_w - gap * (len(r) - 1)) / sum(aspects[i] for i in r) for r in rows]
            total_h = sum(heights) + gap * (len(rows) - 1)
            scale = min(1.0, inner_h / total_h)
            areas = [
                (h * scale) * (aspects[i] * h * scale) for r, h in zip(rows, heights) for i in r
            ]
            score = (min(areas), sum(areas))
            if best is None or score > best[0]:
                best = (score, rows, scale)
    assert best is not None
    _, rows, scale = best

    row_hs, row_ws = [], []
    for r in rows:
        h = ((inner_w - gap * (len(r) - 1)) / sum(aspects[i] for i in r)) * scale
        row_hs.append(h)
        row_ws.append(sum(aspects[i] * h for i in r) + gap * (len(r) - 1))
    y = (height - (sum(row_hs) + gap * (len(rows) - 1))) / 2
    placed: dict[int, tuple[int, int, int, int]] = {}
    for r, h, row_w in zip(rows, row_hs, row_ws):
        x = (width - row_w) / 2
        for i in r:
            w = aspects[i] * h
            placed[i] = (round(x), round(y), round(w), round(h))
            x += w + gap
        y += h + gap
    return [placed[i] for i in range(n)]
