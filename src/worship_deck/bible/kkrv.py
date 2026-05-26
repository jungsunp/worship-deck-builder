"""Fetch 개역한글 verse text from the bundled KorRV dataset.

Source: scrollmapper/bible_databases (MIT); text is public domain
(Korean Revised Version 개역한글, 1961; copyright expired ~2012).
"""

from __future__ import annotations

import json
from pathlib import Path

from worship_deck.bible.ref import BibleRef

_DATA_PATH = Path(__file__).parent / "data" / "krv.json"

# KorRV.json uses Roman-numeral book names; normalise to match BibleRef.book
_NAME_FIX: dict[str, str] = {
    "I Samuel": "1 Samuel",         "II Samuel": "2 Samuel",
    "I Kings": "1 Kings",           "II Kings": "2 Kings",
    "I Chronicles": "1 Chronicles", "II Chronicles": "2 Chronicles",
    "I Corinthians": "1 Corinthians", "II Corinthians": "2 Corinthians",
    "I Thessalonians": "1 Thessalonians", "II Thessalonians": "2 Thessalonians",
    "I Timothy": "1 Timothy",       "II Timothy": "2 Timothy",
    "I Peter": "1 Peter",           "II Peter": "2 Peter",
    "I John": "1 John",             "II John": "2 John",
    "III John": "3 John",           "Revelation of John": "Revelation",
}

_INDEX: dict[str, dict[int, dict[int, str]]] | None = None


def _load() -> dict[str, dict[int, dict[int, str]]]:
    global _INDEX
    if _INDEX is None:
        raw = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
        _INDEX = {}
        for book in raw["books"]:
            name = _NAME_FIX.get(book["name"], book["name"])
            _INDEX[name] = {
                int(ch["chapter"]): {
                    int(v["verse"]): v["text"].strip()
                    for v in ch["verses"]
                }
                for ch in book["chapters"]
            }
    return _INDEX


def fetch_korean(ref: BibleRef) -> str:
    """Return 개역한글 passage text for *ref*, newline-separated for ranges/chapters.

    Raises:
        ValueError: if book, chapter, or verse is absent from the dataset.
    """
    index = _load()
    book = index.get(ref.book)
    if book is None:
        raise ValueError(f"Book not found in KRV dataset: {ref.book!r}")
    chapter = book.get(ref.chapter)
    if chapter is None:
        raise ValueError(f"Chapter not found: {ref.book} {ref.chapter}")

    if ref.verse_start is None:                      # whole chapter
        return "\n".join(chapter[v] for v in sorted(chapter))
    if ref.verse_end is None:                        # single verse
        verse = chapter.get(ref.verse_start)
        if verse is None:
            raise ValueError(f"Verse not found: {ref.book} {ref.chapter}:{ref.verse_start}")
        return verse
    # verse range
    verses = [chapter[v] for v in range(ref.verse_start, ref.verse_end + 1) if v in chapter]
    if not verses:
        raise ValueError(
            f"No verses in range: {ref.book} {ref.chapter}:{ref.verse_start}-{ref.verse_end}"
        )
    return "\n".join(verses)
