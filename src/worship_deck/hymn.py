"""Download a 봉헌 (offering) 찬송가 PowerPoint and convert its slides to PNG.

Source: bibletoppt.com — a free, number-keyed token API (resolved in spike #50).
There is no local hymn directory; every hymn is fetched online per song by its
찬송가 number.

Download is a two-step token flow (the token is a short-lived JWT, ~5 min):

    1. GET /api/download?action=token&type=hymn&design=<design>&number=<number>
         -> {"token": "<JWT>"}
    2. GET /api/download?token=<JWT>
         -> .pptx bytes

A browser ``User-Agent`` header is required — header-less requests get HTTP 403.

The PPT's slides are flat embedded images (no machine-readable verse text), and a
hymn's verses do not map one-to-one to slides. So this module converts *all* slides
to ordered PNGs; dropping unwanted verses is the operator's job in the review UI (#25).

Slide → PNG conversion shells out to two system binaries (no extra pip deps):
LibreOffice ``soffice`` (pptx → pdf) and poppler ``pdftoppm`` (pdf → png).
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

BIBLETOPPT = "https://bibletoppt.com"
DEFAULT_DESIGN = "no-bg"  # 무배경 — cleanest variant; least likely to clash with the template
# The ProPresenter deck's design (#179). "no-bg" renders a solid-white page with the artwork
# pillarboxed into a 4:3 box — right over Keynote's own background, a full-screen white flash in
# the white-on-dark .pro deck. design6 (야자수/종려나무) is full-bleed 16:9 with much larger type,
# and bibletoppt offers no dark design at all. Same source PPTX, so the two renders share a page
# count and pdftoppm filenames — which is what lets propresenter.build swap one for the other.
PRO_DESIGN = "design6"
# A real browser UA is required; bibletoppt returns HTTP 403 to header-less requests.
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def download_hymn_ppt(number: str, dest_dir: Path, design: str = DEFAULT_DESIGN) -> Path:
    """Download the 찬송가 PPT for *number* from bibletoppt; return the saved .pptx path.

    Args:
        number: 찬송가 hymn number, e.g. "220".
        dest_dir: directory to write the .pptx into (created if missing).
        design: bibletoppt design slug (design1–design6, korean-english, no-bg).

    Raises:
        RuntimeError: if the token response has no token.
        httpx.HTTPStatusError: on non-2xx responses.
    """
    import httpx

    headers = {"User-Agent": _UA}

    token_resp = httpx.get(
        f"{BIBLETOPPT}/api/download",
        params={"action": "token", "type": "hymn", "design": design, "number": number},
        headers=headers,
        timeout=20,
        follow_redirects=True,
    )
    token_resp.raise_for_status()
    token = token_resp.json().get("token")
    if not token:
        raise RuntimeError(f"bibletoppt returned no download token for hymn {number}")

    file_resp = httpx.get(
        f"{BIBLETOPPT}/api/download",
        params={"token": token},
        headers=headers,
        timeout=60,
        follow_redirects=True,
    )
    file_resp.raise_for_status()

    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"hymn-{number}.pptx"
    out.write_bytes(file_resp.content)
    return out


def pptx_to_pngs(pptx: Path, out_dir: Path) -> list[Path]:
    """Convert every slide of *pptx* to a PNG in *out_dir*; return ordered paths.

    Shells out to ``soffice`` (pptx → pdf) then ``pdftoppm`` (pdf → png). Requires
    LibreOffice and poppler installed (local only).

    Raises:
        subprocess.CalledProcessError: if soffice or pdftoppm fails.
        FileNotFoundError: if soffice produced no PDF.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        # A throwaway user profile lets soffice run alongside an open LibreOffice/Keynote.
        subprocess.run(
            [
                "soffice",
                "--headless",
                f"-env:UserInstallation=file://{tmp}/profile",
                "--convert-to",
                "pdf",
                "--outdir",
                tmp,
                str(pptx),
            ],
            check=True,
            capture_output=True,
        )
        pdf = Path(tmp) / f"{pptx.stem}.pdf"
        if not pdf.exists():
            raise FileNotFoundError(f"soffice did not produce a PDF for {pptx}")

        subprocess.run(
            ["pdftoppm", "-png", "-r", "150", str(pdf), str(out_dir / "slide")],
            check=True,
            capture_output=True,
        )

    # pdftoppm names pages slide-1.png, slide-2.png … (zero-padded to the page count).
    return sorted(out_dir.glob("slide-*.png"), key=lambda p: int(p.stem.split("-")[-1]))


def fetch_hymn_slides(
    number: str, work_dir: Path, design: str = DEFAULT_DESIGN
) -> list[Path]:
    """Download hymn *number* and convert it to ordered PNG slides under *work_dir*.

    Returns every slide as a PNG (verse selection happens in the review UI, #25).
    """
    pptx = download_hymn_ppt(number, work_dir, design)
    return pptx_to_pngs(pptx, work_dir)


def verse_labels(pptx: Path) -> list[dict]:
    """Which verse each slide of a bibletoppt hymn PPTX shows, in slide (= PNG page) order.

    The slides are flat images, but each carries a separate small "verse dots" picture (the
    1·2·3·4 pager in the corner) that is byte-identical for every page of one verse and differs
    between verses. Grouping slides by that last image therefore gives the verse number (order of
    first appearance) and the page within it: ``{"verse": 2, "page": 1, "pages": 2, "label": "2절 (1/2)"}``
    (no ``(i/k)`` when the verse has a single page). A slide without that picture — or an older
    two-image PPTX layout — gets ``None`` rather than a guess.
    """
    with zipfile.ZipFile(pptx) as z:
        names = z.namelist()
        count = len([n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)])
        keys: list[str | None] = []
        for i in range(1, count + 1):
            rels = z.read(f"ppt/slides/_rels/slide{i}.xml.rels").decode("utf-8")
            media = re.findall(r'Target="\.\./media/([^"]+)"', rels)
            keys.append(hashlib.md5(z.read(f"ppt/media/{media[-1]}")).hexdigest() if len(media) >= 3 else None)
    order = list(dict.fromkeys(k for k in keys if k))
    totals = {k: keys.count(k) for k in order}
    seen: dict[str, int] = {}
    out: list[dict | None] = []
    for k in keys:
        if k is None:
            out.append(None)
            continue
        seen[k] = seen.get(k, 0) + 1
        verse, n = order.index(k) + 1, totals[k]
        label = f"{verse}절" + (f" ({seen[k]}/{n})" if n > 1 else "")
        out.append({"verse": verse, "page": seen[k], "pages": n, "label": label})
    return out
