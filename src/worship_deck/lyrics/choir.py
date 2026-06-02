"""Parse 성가대 (choir) lyrics from pasted raw text — no image, no OCR, no API.

Unlike worship songs (band lead-sheet images run through Vision+Ollama), choir lyrics
arrive as raw text pasted into the review app: a title line, a composer/arranger line
(``… 작곡`` / ``… 편곡``), then lyric lines that already have real line breaks. So this
is a pure string parser — CI-testable, with no Mac/Keynote/Ollama dependency.

``parse_choir_text`` returns the same ``Song`` dataclass as ``lyrics.transcribe``.
Chunking the lines into <= 2-line slides is #18's ``chunk()``; out of scope here.
"""

from __future__ import annotations

import re

from worship_deck.lyrics.transcribe import Song

# The composer/arranger credit line, e.g. "홍길동 작곡 / 김철수 편곡".
_COMPOSER_MARK = re.compile(r"작곡|편곡")


def parse_choir_text(raw: str) -> Song:
    """Parse one pasted choir-song block into a Song.

    The block is a title line + a composer/arranger line + lyric lines (already
    line-broken). The title comes from the first line, the composer line is kept
    for the title slide, and the remaining lines are returned as ordered lyrics.
    Blank lines are dropped.
    """
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return Song(title="")

    title, *rest = lines
    composer = ""
    lyrics: list[str] = []
    for ln in rest:
        if not composer and _COMPOSER_MARK.search(ln):
            composer = ln
        else:
            lyrics.append(ln)
    return Song(title=title, lines=lyrics, composer=composer)
