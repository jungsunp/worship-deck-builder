"""Build the draft deck by driving Keynote.app via AppleScript/JXA.

Requires a Mac that is powered on and logged in. Starting from the template deck, this
duplicates section slides to fit the week's content, places the rendered PNGs and the
existing hymn image slides in order, and saves data/drafts/draft-YYYY-MM-DD.key plus a
PDF preview for phone review. AppleScript sources live in ./applescript/.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_SAVE_DRAFT = Path(__file__).parent / "applescript" / "save_draft.applescript"


def save_draft(template_key: str, out_key: str) -> str:
    """Open the template deck and save a copy to out_key, returning out_key.

    The first Keynote primitive (#20): proves we can drive Keynote over AppleScript.
    Save-As leaves the template untouched. Later issues (#21, #13–16) extend this plumbing
    to duplicate slides and set native text.

    Raises:
        RuntimeError: if `osascript` is missing (not macOS) or the Keynote save fails.
    """
    template = str(Path(template_key).expanduser())
    out = str(Path(out_key).expanduser())
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            ["osascript", str(_SAVE_DRAFT), template, out],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError as e:  # `osascript` only exists on macOS
        raise RuntimeError("`osascript` not found — Keynote automation needs macOS.") from e
    if result.returncode != 0:
        raise RuntimeError(f"Keynote save failed: {result.stderr.strip()}")
    return out_key


def build(template_key: str, slides: list[dict], out_key: str) -> str:
    """Generate a fresh deck from the template with the given ordered slides."""
    raise NotImplementedError


def export_pdf(key_path: str, out_pdf: str) -> str:
    """Export a deck to PDF for phone preview."""
    raise NotImplementedError
