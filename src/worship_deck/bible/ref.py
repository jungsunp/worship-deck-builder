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

# Full Korean book names also appear in bulletins (e.g. the sermon ref "요한복음 4:43-54"),
# so accept them alongside the abbreviations above. Merged into _KOREAN_BOOKS below so both
# parse_ref() and the bulletin ref-stripping regexes recognize either form, and kept as a
# constant of its own so korean_ref() can spell an abbreviation back out.
_KOREAN_FULL_BOOKS: dict[str, str] = {
    "창세기": "Genesis", "출애굽기": "Exodus", "레위기": "Leviticus", "민수기": "Numbers",
    "신명기": "Deuteronomy", "여호수아": "Joshua", "사사기": "Judges", "룻기": "Ruth",
    "사무엘상": "1 Samuel", "사무엘하": "2 Samuel", "열왕기상": "1 Kings", "열왕기하": "2 Kings",
    "역대상": "1 Chronicles", "역대하": "2 Chronicles", "에스라": "Ezra", "느헤미야": "Nehemiah",
    "에스더": "Esther", "욥기": "Job", "시편": "Psalms", "잠언": "Proverbs", "전도서": "Ecclesiastes",
    "아가": "Song of Solomon", "이사야": "Isaiah", "예레미야": "Jeremiah", "예레미야애가": "Lamentations",
    "에스겔": "Ezekiel", "다니엘": "Daniel", "호세아": "Hosea", "요엘": "Joel", "아모스": "Amos",
    "오바댜": "Obadiah", "요나": "Jonah", "미가": "Micah", "나훔": "Nahum", "하박국": "Habakkuk",
    "스바냐": "Zephaniah", "학개": "Haggai", "스가랴": "Zechariah", "말라기": "Malachi",
    "마태복음": "Matthew", "마가복음": "Mark", "누가복음": "Luke", "요한복음": "John",
    "사도행전": "Acts", "로마서": "Romans", "고린도전서": "1 Corinthians", "고린도후서": "2 Corinthians",
    "갈라디아서": "Galatians", "에베소서": "Ephesians", "빌립보서": "Philippians", "골로새서": "Colossians",
    "데살로니가전서": "1 Thessalonians", "데살로니가후서": "2 Thessalonians",
    "디모데전서": "1 Timothy", "디모데후서": "2 Timothy", "디도서": "Titus", "빌레몬서": "Philemon",
    "히브리서": "Hebrews", "야고보서": "James", "베드로전서": "1 Peter", "베드로후서": "2 Peter",
    "요한일서": "1 John", "요한이서": "2 John", "요한삼서": "3 John", "유다서": "Jude",
    "요한계시록": "Revelation",
}
_KOREAN_BOOKS.update(_KOREAN_FULL_BOOKS)

# The inverse, for korean_ref(): canonical English name -> full Korean name.
_FULL_BY_ENGLISH: dict[str, str] = {en: ko for ko, en in _KOREAN_FULL_BOOKS.items()}

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


def korean_ref(reference: str) -> str:
    """Spell a reference's book out in full Korean: "삼상 14:23-52" -> "사무엘상 14:23-52".

    Bulletins abbreviate, and the verse plates keep that: their reference is a small heading
    read at a glance beside the 개역한글/ESV label, where 삼상 is what the congregation is used
    to. A **divider** is the opposite — one line of type across the whole screen announcing
    what is about to be read — and there the abbreviation reads as a shorthand nobody needs
    (#250). So the abbreviation stays on the small headings and the full name goes on the plates.

    Returns ``reference`` unchanged when it can't be parsed or the book isn't recognized: a
    divider subtitle is decoration, and a week with an odd reference should still build.
    """
    m = _REF_RE.match(reference.strip())
    if not m:
        return reference
    english = _KOREAN_BOOKS.get(m.group("book"))
    if english is None:
        return reference
    return f"{_FULL_BY_ENGLISH[english]} {reference.strip()[m.end('book'):].lstrip()}"
