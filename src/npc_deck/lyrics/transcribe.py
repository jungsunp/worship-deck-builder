"""Transcribe lyrics from band/choir sheet images and chunk them into slides.

Band sheets arrive as images/PDFs with musical notation; Claude vision reads the Korean
lyrics, reconstructs full lines (de-hyphenating syllables split across notes) and verse
order, then we chunk into <= 2-line slides. Song-to-slot matching uses the bulletin's
worship order. The user confirms order/breaks in the web app before building.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Song:
    title: str
    slides: list[str] = field(default_factory=list)  # each entry = up to 2 lines


def transcribe(image_path: str) -> Song:
    """Read one sheet image into an ordered Song (Claude vision)."""
    raise NotImplementedError


def chunk(lines: list[str], max_lines: int = 2) -> list[str]:
    """Group lyric lines into <= max_lines per slide."""
    raise NotImplementedError
