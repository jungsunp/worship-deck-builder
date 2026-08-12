"""Parse 성가대 (choir) lyrics from pasted raw text — no image, no OCR, no API.

Unlike worship songs (band lead-sheet images run through Vision OCR + gasazip), choir lyrics
arrive as raw text pasted into the review app: a title line, a composer/arranger line
(``… 작곡`` / ``… 편곡``), then lyric lines that already have real line breaks. So this
is a pure string parser — CI-testable, with no Mac/Keynote/network dependency.

``parse_choir_text`` returns the same ``Song`` dataclass as ``lyrics.transcribe``.
The ``lines`` it returns are fed to ``lyrics.transcribe.chunk()``, which treats a
blank line as a stanza break — so blank lines between stanzas are *preserved* here
(only the leading/trailing ones are trimmed) to keep each stanza on its own slide.
"""

from __future__ import annotations

import re

from worship_deck.lyrics.transcribe import Song, strip_zero_width

# The composer/arranger credit line, e.g. "홍길동 작곡 / 김철수 편곡".
_COMPOSER_MARK = re.compile(r"작곡|편곡")
# Interlude marker, e.g. "간주" or "(간주)" — dropped, matching how master.key omits it.
_INTERLUDE = re.compile(r"^\(?간주\)?$")


def parse_choir_text(raw: str) -> Song:
    """Parse one pasted choir-song block into a Song.

    The block is a title line + a composer/arranger line + lyric lines (already
    line-broken). The title comes from the first non-blank line, the composer line is
    kept for the title slide, and the remaining lines are returned as ordered lyrics.
    The composer is a ``작곡``/``편곡`` credit line; when neither marker is present (e.g.
    an English name like "Stan Pethel"), the line directly after the title is taken as
    the composer only when it stands alone — set off from the lyrics by a blank line — so
    a multi-line first stanza with no credit is not mistaken for one. Blank lines between
    stanzas are preserved (leading/trailing ones trimmed) so ``chunk()`` keeps each
    stanza on its own slide; interlude markers (``간주``) are dropped, and zero-width
    characters are stripped so an invisible "blank" line reads as a real stanza break.
    """
    # Zero-width chars first: the pasted source separates stanzas with U+200B-only lines,
    # which `strip()` alone leaves non-blank (they then land on a slide as a lyric line).
    lines = [strip_zero_width(ln).strip() for ln in raw.splitlines()]

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
    body = rest
    mark = next((i for i, ln in enumerate(rest) if _COMPOSER_MARK.search(ln)), None)
    if mark is not None:
        composer = rest[mark]
        body = rest[:mark] + rest[mark + 1 :]
    elif rest and rest[0] and (len(rest) == 1 or not rest[1]):
        composer = rest[0]
        body = rest[1:]

    lyrics = [ln for ln in body if not _INTERLUDE.match(ln)]

    # Trim leading/trailing blanks; interior blanks stay as stanza breaks for chunk().
    while lyrics and not lyrics[0]:
        lyrics.pop(0)
    while lyrics and not lyrics[-1]:
        lyrics.pop()
    return Song(title=title, lines=lyrics, composer=composer)
