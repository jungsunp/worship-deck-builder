"""Parse 성가대 (choir) lyrics from pasted raw text — no image, no OCR, no API.

Unlike worship songs (band lead-sheet images run through Vision+Ollama), choir lyrics
arrive as raw text pasted into the review app: a title line, a composer/arranger line
(``… 작곡`` / ``… 편곡``), then lyric lines that already have real line breaks. So this
is a pure string parser — CI-testable, with no Mac/Keynote/Ollama dependency.

``parse_choir_text`` returns the same ``Song`` dataclass as ``lyrics.transcribe``.
The ``lines`` it returns are fed to ``lyrics.transcribe.chunk()``, which treats a
blank line as a stanza break — so blank lines between stanzas are *preserved* here
(only the leading/trailing ones are trimmed) to keep each stanza on its own slide.
"""

from __future__ import annotations

import re

from worship_deck.lyrics.transcribe import Song

# The composer/arranger credit line, e.g. "홍길동 작곡 / 김철수 편곡".
_COMPOSER_MARK = re.compile(r"작곡|편곡")
# Interlude marker, e.g. "간주" or "(간주)" — dropped, matching how master.key omits it.
_INTERLUDE = re.compile(r"^\(?간주\)?$")


def parse_choir_text(raw: str) -> Song:
    """Parse one pasted choir-song block into a Song.

    The block is a title line + a composer/arranger line + lyric lines (already
    line-broken). The title comes from the first non-blank line, the composer line is
    kept for the title slide, and the remaining lines are returned as ordered lyrics.
    Blank lines between stanzas are preserved (leading/trailing ones trimmed) so
    ``chunk()`` keeps each stanza on its own slide; interlude markers (``간주``) are
    dropped.
    """
    lines = [ln.strip() for ln in raw.splitlines()]

    title = ""
    rest: list[str] = []
    for i, ln in enumerate(lines):
        if ln:
            title = ln
            rest = lines[i + 1 :]
            break
    if not title:
        return Song(title="")

    composer = ""
    lyrics: list[str] = []
    for ln in rest:
        if not composer and _COMPOSER_MARK.search(ln):
            composer = ln
        elif _INTERLUDE.match(ln):
            continue
        else:
            lyrics.append(ln)

    # Trim leading/trailing blanks; interior blanks stay as stanza breaks for chunk().
    while lyrics and not lyrics[0]:
        lyrics.pop(0)
    while lyrics and not lyrics[-1]:
        lyrics.pop()
    return Song(title=title, lines=lyrics, composer=composer)
