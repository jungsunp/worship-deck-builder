"""Parse the weekly bulletin PDF into structured service data.

Extracts: service date, worship order (song titles + who leads each part),
announcements (교회소식), Bible references for 예배의 부름 and 말씀, and sermon title.
The bulletin layout is stable week to week, so text extraction is reliable.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from worship_deck.bible.ref import _KOREAN_BOOKS as _BOOKS

# ── Module-level constants ────────────────────────────────────────────────────

# Sorted longest-first so alternation matches greedily (e.g. "삼상" before "삼")
_BOOK_PAT = "|".join(re.escape(k) for k in sorted(_BOOKS, key=len, reverse=True))
# Parenthesized Bible ref: (눅 22:14-24) — stripped from song titles in _split_content
_PAREN_REF_RE = re.compile(r"\((?:" + _BOOK_PAT + r")\s+\d[\d:,\-]*\)")
# Inline Bible ref at start of content: "시 133:1-3 홍길동 목사"
_INLINE_REF_RE = re.compile(r"^(?:" + _BOOK_PAT + r")\s+\d[\d:,\-]*")

_TITLE_SUFFIXES = {"목사", "전도사", "집사", "장로", "권사", "사모"}
_LEADER_TOKENS = {"다함께", "성가대"}

# Worship order table x-coordinate boundaries (absolute page pts, 14" × 8.5" bulletin)
_X_SPLIT = 105   # left of this → part name cell; right → content cell
_X_RIGHT = 323   # right edge of the left column


@dataclass
class ServiceData:
    date: str = ""
    worship_order: list[dict] = field(default_factory=list)
    announcements: list[str] = field(default_factory=list)
    call_to_worship_ref: str = ""
    sermon_title: str = ""
    sermon_ref: str = ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _split_content(content: str) -> tuple[str, str]:
    """Split a worship order row's right-column text into (title, leader).

    'title' is the display title for that element (song title, sermon title,
    creed name, etc.) — empty when the row has no displayable title.
    Parenthesized Bible refs like (눅 22:14-24) are stripped so they don't
    contaminate the title (those refs are surfaced by issue #7).
    Inline refs at the start ("시 133:1-3 …") mean there is no title.
    """
    # 1. Strip parenthesized Bible refs
    content = re.sub(r"\s+", " ", _PAREN_REF_RE.sub("", content)).strip()

    # 2. Inline ref at start → no title; remainder is leader
    if _INLINE_REF_RE.match(content):
        rest = _INLINE_REF_RE.sub("", content).strip()
        return "", rest

    # 3. Peel off leader from the end
    tokens = content.split()
    if not tokens:
        return "", ""
    if tokens[-1] in _LEADER_TOKENS:
        return " ".join(tokens[:-1]).strip(), tokens[-1]
    if len(tokens) >= 2 and tokens[-1] in _TITLE_SUFFIXES:
        return " ".join(tokens[:-2]).strip(), " ".join(tokens[-2:])
    return content, ""


def _parse_worship_order(page) -> list[dict]:
    """Extract the main worship order from page 1's left column.

    The worship order is a two-cell <table> (part name | content) sandwiched
    between two <hr> elements.  pdfplumber renders those <hr>s as thin filled
    rects, which we use as Y-range anchors.  Words are then split at _X_SPLIT
    to separate the part-name cell from the content cell.
    """
    # Find the two thin horizontal rules in the left column
    left_hrs = sorted(
        [r for r in page.rects if r["x0"] < 100 and r["x1"] < 400 and r["height"] < 2],
        key=lambda r: r["top"],
    )
    if len(left_hrs) < 2:
        return []
    hr1_top, hr2_top = left_hrs[0]["top"], left_hrs[1]["top"]

    # Words inside the left column, between the two hrs
    section_words = [
        w for w in page.extract_words()
        if w["x0"] < _X_RIGHT and hr1_top < w["top"] < hr2_top
    ]

    # Group words by row (integer top)
    rows: dict[int, dict] = {}
    for w in section_words:
        top = round(w["top"])
        if top not in rows:
            rows[top] = {"left": [], "right": []}
        rows[top]["left" if w["x0"] < _X_SPLIT else "right"].append(w["text"])

    # Parse each row
    result = []
    for top in sorted(rows):
        part_raw = " ".join(rows[top]["left"])
        content = " ".join(rows[top]["right"])
        if not part_raw or part_raw.startswith("(*"):
            continue  # skip empty rows and the (*표는…) footnote
        part = part_raw.rstrip("*").strip()
        title, leader = _split_content(content)
        result.append({"part": part, "title": title, "leader": leader})
    return result


def _parse_announcements(page) -> list[str]:
    """Extract numbered announcement titles from the middle column of page 1.

    Each announcement is an <h3> in the HTML source rendered as "N. Title text".
    The middle column sits at x0 339–724; the right column (기도제목) starts at
    x0 ~724 so there is no overlap.  Only lines matching r'^\\d+\\.' are titles.
    """
    mid_words = [w for w in page.extract_words() if 339 <= w["x0"] < 724]

    rows: dict[int, list[str]] = {}
    for w in mid_words:
        rows.setdefault(round(w["top"]), []).append(w["text"])

    announcements = []
    for top in sorted(rows):
        line = " ".join(rows[top])
        m = re.match(r"^\d+\.\s+(.+)", line)
        if m:
            announcements.append(m.group(1).strip())
    return announcements


# ── Public API ────────────────────────────────────────────────────────────────

def parse(pdf_path: str) -> ServiceData:
    """Parse a bulletin PDF into ServiceData. (pdfplumber)"""
    import pdfplumber

    logging.disable(logging.WARNING)
    try:
        with pdfplumber.open(pdf_path) as pdf:
            text = "".join(p.extract_text() or "" for p in pdf.pages)
            worship_order = _parse_worship_order(pdf.pages[0])
            announcements = _parse_announcements(pdf.pages[0])
    finally:
        logging.disable(logging.NOTSET)

    date_match = re.search(r"\d{4}년\s*\d{1,2}월\s*\d{1,2}일", text)
    date = re.sub(r"\s+", " ", date_match.group()) if date_match else ""

    return ServiceData(date=date, worship_order=worship_order, announcements=announcements)
