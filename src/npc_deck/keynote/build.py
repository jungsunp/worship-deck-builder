"""Build the draft deck by driving Keynote.app via AppleScript/JXA.

Requires a Mac that is powered on and logged in. Starting from the template deck, this
duplicates section slides to fit the week's content, places the rendered PNGs and the
existing hymn image slides in order, and saves data/drafts/draft-YYYY-MM-DD.key plus a
PDF preview for phone review. AppleScript sources live in ./applescript/.
"""

from __future__ import annotations


def build(template_key: str, slides: list[dict], out_key: str) -> str:
    """Generate a fresh deck from the template with the given ordered slides."""
    raise NotImplementedError


def export_pdf(key_path: str, out_pdf: str) -> str:
    """Export a deck to PDF for phone preview."""
    raise NotImplementedError
