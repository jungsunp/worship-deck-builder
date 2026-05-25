"""Parse Korean-style Bible references into a normalized form.

Examples:
    "시 133"       -> BibleRef("Psalms", 133, None, None)
    "눅 22:14-24"  -> BibleRef("Luke", 22, 14, 24)
    "눅 22:14"     -> BibleRef("Luke", 22, 14, None)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_KOREAN_BOOKS: dict[str, str] = {
    # Old Testament
    "창": "Genesis",
    "출": "Exodus",
    "레": "Leviticus",
    "민": "Numbers",
    "신": "Deuteronomy",
    "수": "Joshua",
    "삿": "Judges",
    "룻": "Ruth",
    "삼상": "1 Samuel",
    "삼하": "2 Samuel",
    "왕상": "1 Kings",
    "왕하": "2 Kings",
    "대상": "1 Chronicles",
    "대하": "2 Chronicles",
    "스": "Ezra",
    "느": "Nehemiah",
    "에": "Esther",
    "욥": "Job",
    "시": "Psalms",
    "잠": "Proverbs",
    "전": "Ecclesiastes",
    "아": "Song of Solomon",
    "사": "Isaiah",
    "렘": "Jeremiah",
    "애": "Lamentations",
    "겔": "Ezekiel",
    "단": "Daniel",
    "호": "Hosea",
    "욜": "Joel",
    "암": "Amos",
    "옵": "Obadiah",
    "욘": "Jonah",
    "미": "Micah",
    "나": "Nahum",
    "합": "Habakkuk",
    "습": "Zephaniah",
    "학": "Haggai",
    "슥": "Zechariah",
    "말": "Malachi",
    # New Testament
    "마": "Matthew",
    "막": "Mark",
    "눅": "Luke",
    "요": "John",
    "행": "Acts",
    "롬": "Romans",
    "고전": "1 Corinthians",
    "고후": "2 Corinthians",
    "갈": "Galatians",
    "엡": "Ephesians",
    "빌": "Philippians",
    "골": "Colossians",
    "살전": "1 Thessalonians",
    "살후": "2 Thessalonians",
    "딤전": "1 Timothy",
    "딤후": "2 Timothy",
    "딛": "Titus",
    "몬": "Philemon",
    "히": "Hebrews",
    "약": "James",
    "벧전": "1 Peter",
    "벧후": "2 Peter",
    "요일": "1 John",
    "요이": "2 John",
    "요삼": "3 John",
    "유": "Jude",
    "계": "Revelation",
}

_REF_RE = re.compile(
    r"^(?P<book>\S+)\s+(?P<chapter>\d+)(?::(?P<vs>\d+)(?:-(?P<ve>\d+))?)?$"
)


@dataclass(frozen=True)
class BibleRef:
    book: str             # English canonical name, e.g. "Luke", "Psalms"
    chapter: int
    verse_start: int | None   # None for chapter-only refs like "시 133"
    verse_end: int | None     # None when no range (single verse or whole chapter)


def parse_ref(reference: str) -> BibleRef:
    """Parse a Korean-style Bible reference string into a BibleRef.

    Args:
        reference: e.g. "시 133", "눅 22:14-24", "눅 22:14"

    Raises:
        ValueError: if the format is unrecognizable or the book abbreviation is unknown.
    """
    m = _REF_RE.match(reference.strip())
    if not m:
        raise ValueError(f"Unrecognizable Bible reference: {reference!r}")

    book_token = m.group("book")
    if book_token not in _KOREAN_BOOKS:
        raise ValueError(f"Unknown Korean book abbreviation: {book_token!r}")

    vs = m.group("vs")
    ve = m.group("ve")
    return BibleRef(
        book=_KOREAN_BOOKS[book_token],
        chapter=int(m.group("chapter")),
        verse_start=int(vs) if vs is not None else None,
        verse_end=int(ve) if ve is not None else None,
    )
