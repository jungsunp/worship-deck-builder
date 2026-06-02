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
_DUPLICATE_SLIDE = Path(__file__).parent / "applescript" / "duplicate_slide.applescript"


def _run_osascript(script: Path, *args: str) -> str:
    """Run an AppleScript file via osascript, returning its stdout.

    Raises:
        RuntimeError: if `osascript` is missing (not macOS) or the script fails.
    """
    try:
        result = subprocess.run(
            ["osascript", str(script), *args],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError as e:  # `osascript` only exists on macOS
        raise RuntimeError("`osascript` not found — Keynote automation needs macOS.") from e
    if result.returncode != 0:
        raise RuntimeError(f"Keynote script {script.name} failed: {result.stderr.strip()}")
    return result.stdout


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
    _run_osascript(_SAVE_DRAFT, template, out)
    return out_key


def duplicate_slide(key_path: str, slide_index: int, count: int) -> int:
    """Duplicate the 1-based slide at slide_index `count` times, in place.

    The second Keynote primitive (#21): expands a one-slide section template into the
    week's lyric/announcement slides (#15/#16 then fill each copy's native text). Copies
    land contiguously after the source slide. Returns the resulting total slide count.

    Raises:
        RuntimeError: if `osascript` is missing (not macOS) or the Keynote script fails.
    """
    key = str(Path(key_path).expanduser())
    out = _run_osascript(_DUPLICATE_SLIDE, key, str(slide_index), str(count))
    return int(out.strip())


def build(template_key: str, slides: list[dict], out_key: str) -> str:
    """Generate a fresh deck from the template with the given ordered slides."""
    raise NotImplementedError


def export_pdf(key_path: str, out_pdf: str) -> str:
    """Export a deck to PDF for phone preview."""
    raise NotImplementedError
