"""Extract the 4 clean (text-free) slide backgrounds from the master Keynote deck.

Run once on a Mac whenever the master deck's backgrounds change; commit the outputs.

    python scripts/extract_backgrounds.py

Requires macOS + Keynote (drives it via AppleScript). The renderer (render.render)
flattens every congregation slide onto one of these backgrounds, so they live as
committed source assets under src/worship_deck/render/templates/.

The deck is opened, every text item is stripped off all slides, the result is
exported as slide images, and the 4 chosen slides are copied out by type. The deck
is closed WITHOUT saving, so master.key on disk is never modified.

Slide anchors default to last week's 170-slide reference deck; override per type if
the master differs (verify the 4 PNGs look right and re-run with corrected indices):

    python scripts/extract_backgrounds.py --lyrics 9 --announcement 118
"""

from __future__ import annotations

import argparse
import glob
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).parent.parent
TEMPLATES_DIR = REPO / "src" / "worship_deck" / "render" / "templates"
DEFAULT_DECK = REPO / "templates" / "master.key"

# slide_map.yaml anchors in last week's reference deck. The 7 rendered_image
# sections collapse to these 4 distinct backgrounds.
ANCHORS = {"date": 1, "verse": 48, "lyrics": 8, "announcement": 117}


def resolve_deck() -> Path:
    env = os.getenv("TEMPLATE_KEY")
    deck = Path(env).expanduser() if env else DEFAULT_DECK
    if not deck.exists():
        sys.exit(f"Master deck not found: {deck} (set TEMPLATE_KEY or place templates/master.key)")
    return deck


def export_stripped_slides(deck: Path, out_dir: Path) -> list[Path]:
    """Open deck, delete all text, export slides as PNG to out_dir, close without saving."""
    # Delete free text boxes by reverse index (a forward/bulk delete invalidates the
    # element references mid-loop and silently no-ops), then clear the title/body
    # placeholders, which aren't part of `text items`.
    script = f"""\
tell application "Keynote"
    set theDoc to open POSIX file "{deck}"
    repeat with s in slides of theDoc
        repeat with i from (count of text items of s) to 1 by -1
            try
                delete text item i of s
            end try
        end repeat
        try
            set object text of default title item of s to ""
        end try
        try
            set object text of default body item of s to ""
        end try
    end repeat
    export theDoc to POSIX file "{out_dir}" as slide images with properties ¬
        {{image format:PNG, skipped slides:false}}
    close theDoc saving no
end tell
"""
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"AppleScript failed:\n{result.stderr}")
    # Slide images export in order with zero-padded numbers, so sorting = slide order.
    pngs = sorted(Path(p) for p in glob.glob(str(out_dir / "**" / "*.png"), recursive=True))
    if not pngs:
        sys.exit(f"Keynote produced no PNGs in {out_dir}")
    return pngs


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    for name, default in ANCHORS.items():
        ap.add_argument(f"--{name}", type=int, default=default,
                        help=f"1-based slide index for the {name} background (default {default})")
    args = ap.parse_args()
    indices = {name: getattr(args, name) for name in ANCHORS}

    deck = resolve_deck()
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        pngs = export_stripped_slides(deck, Path(tmp))
        for name, idx in indices.items():
            if not 1 <= idx <= len(pngs):
                sys.exit(f"--{name} {idx} out of range (deck exported {len(pngs)} slides)")
            dest = TEMPLATES_DIR / f"{name}.png"
            shutil.copy2(pngs[idx - 1], dest)
            print(f"  {name:12s} <- slide {idx:<3d} -> {dest}")

    print(f"\nDone. Open the 4 PNGs in {TEMPLATES_DIR} and confirm each is the correct,")
    print("text-free background. If an anchor was wrong for this deck, re-run with --<type> N.")


if __name__ == "__main__":
    main()
