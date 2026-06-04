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

import subprocess
import tempfile
from pathlib import Path

BIBLETOPPT = "https://bibletoppt.com"
DEFAULT_DESIGN = "no-bg"  # 무배경 — cleanest variant; least likely to clash with the template
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
