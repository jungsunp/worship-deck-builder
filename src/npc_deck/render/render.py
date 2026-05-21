"""Render a slide's data onto a background template -> PNG.

The church's congregation slides are flattened text-on-background images, so we reproduce
that: a Jinja2 HTML/CSS template per slide type (intro_date, verse, lyrics, announcement)
is filled with data and screenshotted to PNG via Playwright (good Korean typography +
precise 2-line layout). The PNG is then placed into the deck by keynote.build.

Templates live in templates/ ; backgrounds extracted from the existing deck.
"""

from __future__ import annotations


def render(slide_type: str, data: dict, out_path: str) -> str:
    """Render `data` with the `slide_type` template to a PNG at out_path."""
    raise NotImplementedError
