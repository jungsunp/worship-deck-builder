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

# 봉헌 hymn number (찬220, 찬 70장) in the row title
_HYMN_NUM_RE = re.compile(r"찬\s*(\d+)\s*장?")

# Worship order table x-coordinate boundaries (absolute page pts, 14" × 8.5" bulletin).
# The left column holds the order; part-name cells sit at x≲66, content cells at x≳120, and
# the middle (교회소식) column starts at x≈348 — so _X_RIGHT cleanly excludes it.
_X_SPLIT = 105   # left of this → part name cell; right → content cell
_X_RIGHT = 340   # right edge of the left column
# Words inside a part name are ~2–4pt apart; a wider gap means a gutter label sitting between the
# part and content columns (e.g. the sermon-series prefix "왜" before 말 씀, #104) — not the part.
_PART_GAP = 16

# Worship rows jitter by ~2px between the part-name and content cells, so words are clustered
# into a row when their tops fall within this many points of each other.
_ROW_JITTER = 8

# Announcement (교회소식) middle-column bounds: the column sits at x≈348–688 and the 기도제목
# (prayer-topics) column begins at x≈694, so _MID_RIGHT must stay left of it. Each rendered row
# is one intended line (the bulletin breaks lines by hand), so rows are kept as-is.
_MID_LEFT, _MID_RIGHT = 339, 692


@dataclass
class ServiceData:
    date: str = ""
    # Ordered skeleton of the service — one {part, title, leader, ref} dict per row. The heavy
    # per-section content (lyrics, verses) lives in the top-level fields below, keyed to a row by
    # its part; the review UI joins them back in order.
    worship_order: list[dict] = field(default_factory=list)
    # 찬양 medley — one Song-as-dict per song (the opening congregational 찬양 slot). Transcribed
    # from the band lead sheet at assemble; reordered / line-break-fixed in review.
    worship_songs: list[dict] = field(default_factory=list)
    # 성가대 choir song (Song-as-dict); parsed from the inbox choir.txt at assemble. {} until set.
    choir_song: dict = field(default_factory=dict)
    # 고백의 찬양 (Song-as-dict); transcribed from the uploaded sheet image at assemble (#109).
    confession_song: dict = field(default_factory=dict)
    # 예배의 부름 / 말씀 verse passages — one Verse-as-dict each (개역한글 + ESV), looked up at assemble.
    call_to_worship_passage: list[dict] = field(default_factory=list)
    sermon_passage: list[dict] = field(default_factory=list)
    # One slide-ready block per 교회소식 item: "N. title\n\ndetail lines" (gold title, white detail).
    announcements: list[str] = field(default_factory=list)
    call_to_worship_ref: str = ""
    sermon_title: str = ""
    sermon_ref: str = ""
    offering_hymn_number: str = ""
    offering_hymn_title: str = ""
    # Not in the bulletin; set in the review app. Empty = sing all verses.
    offering_hymn_verses: list[int] = field(default_factory=list)
    # Ordered PNG paths for every hymn slide (hymn.fetch_hymn_slides); the
    # operator drops unwanted verse slides in the review app (#25).
    offering_hymn_images: list[str] = field(default_factory=list)
    # Extra sermon refs typed in review (#114); looked up to parallel Verse-dict lists on save
    # (PUT /runs). Not in the bulletin — pure-human fields, preserved across re-assembles.
    sermon_extra_refs: list[str] = field(default_factory=list)
    sermon_extra_passages: list[list[dict]] = field(default_factory=list)
    # Names of parsed/transcribed fields the operator has hand-edited in review; a re-assemble
    # preserves these instead of overwriting them (#105). Set by PUT /runs.
    edited_fields: list[str] = field(default_factory=list)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _split_content(content: str) -> tuple[str, str, str]:
    """Split a worship order row's right-column text into (title, leader, ref).

    'title' is the display title for that element (song title, sermon title,
    creed name, etc.) — empty when the row has no displayable title.
    'ref' is the bare Bible reference (e.g. "눅 22:14-24") found in the row,
    or "" when there is none.  Parenthesized refs like (눅 22:14-24) and inline
    refs at the start ("시 133:1-3 …") are both pulled out so they don't
    contaminate the title.  An inline ref at the start means there is no title.
    """
    # 1. Strip parenthesized Bible refs, capturing the ref text
    paren = _PAREN_REF_RE.search(content)
    ref = paren.group().strip("() ") if paren else ""
    content = re.sub(r"\s+", " ", _PAREN_REF_RE.sub("", content)).strip()

    # 2. Inline ref at start → no title; remainder is leader
    inline = _INLINE_REF_RE.match(content)
    if inline:
        rest = _INLINE_REF_RE.sub("", content).strip()
        return "", rest, inline.group()

    # 3. Peel off the leader. The leader (다함께/성가대) lives in its own sub-column and can land
    #    before or after the title once the row's cells are flattened, so pull it from anywhere;
    #    otherwise take a trailing name + title-suffix ("황인섭 목사").
    tokens = content.split()
    leader = [t for t in tokens if t in _LEADER_TOKENS]
    tokens = [t for t in tokens if t not in _LEADER_TOKENS]
    if not leader and len(tokens) >= 2 and tokens[-1] in _TITLE_SUFFIXES:
        leader, tokens = tokens[-2:], tokens[:-2]
    return " ".join(tokens).strip(), " ".join(leader).strip(), ref


def _parse_offering_hymn(title: str) -> tuple[str, str]:
    """Split a 봉헌 row title into (hymn number, hymn title).

    Handles both bulletin shapes:
      "피난처 있으니 (찬 70장)"     → ("70", "피난처 있으니")
      "찬220. 사랑하는 주님 앞에"   → ("220", "사랑하는 주님 앞에")
    The bulletin never carries a verse selection — that is an internal team
    detail entered (optionally) in the review app; absent it, all verses sing.
    """
    num = _HYMN_NUM_RE.search(title)
    number = num.group(1) if num else ""

    rest = title[: num.start()] + title[num.end() :] if num else title
    rest = re.sub(r"\s+", " ", re.sub(r"[()]", " ", rest)).strip(" .·,")
    return number, rest


def _worship_grid_bottom(page) -> float:
    """Y of the worship-order table's last horizontal rule.

    The order is a bordered table whose per-row rules pdfplumber sees as horizontal
    *lines* (or, in older layouts, thin filled rects). The first contiguous run of
    left-column rules is that table; the next table below starts after a clear gap, so
    we return the last rule of the run as the bottom of the worship order.
    """
    rules = sorted(
        [ln["top"] for ln in page.lines
         if abs(ln["top"] - ln["bottom"]) < 2 and ln["x0"] < 120 and ln["x1"] - ln["x0"] > 150]
        + [r["top"] for r in page.rects
           if r["height"] < 2 and r["x0"] < 120 and r["x1"] - r["x0"] > 150]
    )
    if not rules:
        return page.height
    bottom = rules[0]
    for y in rules[1:]:
        if y - bottom > 28:  # gap to the next table below the order
            break
        bottom = y
    return bottom


def _cluster_rows(words: list[dict]) -> list[list[dict]]:
    """Group words into rows: a new row begins when the top jumps more than _ROW_JITTER."""
    rows: list[list[dict]] = []
    prev_top = None
    for w in sorted(words, key=lambda w: w["top"]):
        if prev_top is None or w["top"] - prev_top > _ROW_JITTER:
            rows.append([])
        rows[-1].append(w)
        prev_top = w["top"]
    return rows


def _part_cell(part_words: list[dict]) -> tuple[str, list[str]]:
    """Split the part-name cell into (part name, gutter words).

    Real part names are a tight run of words at the left margin; a word separated by more than
    _PART_GAP sits in the gutter between the part and content columns — a sermon-series prefix that
    leads the content title (e.g. "왜" before 그럼 그 때는…, #104). Such words belong to the content,
    so they are returned separately to be prepended there — not glued onto the part name. The part's
    trailing "*" footnote mark is stripped.
    """
    s = sorted(part_words, key=lambda w: w["x0"])
    i = next((k for k in range(1, len(s)) if s[k]["x0"] - s[k - 1]["x1"] > _PART_GAP), len(s))
    part = " ".join(w["text"] for w in s[:i]).rstrip("*").strip()
    return part, [w["text"] for w in s[i:]]


def _parse_worship_order(page) -> list[dict]:
    """Extract the main worship order from page 1's left column.

    The order is a (part name | content) table down the left column. Words above the
    table bottom (_worship_grid_bottom) are clustered into rows — cells in a row jitter a
    couple points vertically — then split at _X_SPLIT into the part-name and content cells.
    The column title and the "인도:" leader line carry no content cell and are skipped.
    """
    words = [
        w for w in page.extract_words()
        if w["x0"] < _X_RIGHT and w["top"] < _worship_grid_bottom(page) + 6
    ]

    result = []
    for row in _cluster_rows(words):
        row.sort(key=lambda w: (w["top"], w["x0"]))
        part, gutter = _part_cell([w for w in row if w["x0"] < _X_SPLIT])
        content = " ".join(gutter + [w["text"] for w in row if w["x0"] >= _X_SPLIT])
        if not content or not part or part.startswith("인도") or part.startswith("(*"):
            continue  # column title, the 인도 line, the (*표는…) footnote
        title, leader, ref = _split_content(content)
        result.append({"part": part, "title": title, "leader": leader, "ref": ref})
    return result


def _extract_announcements(page) -> list[dict]:
    """Extract the middle-column 교회소식 items as {number, title, detail} dicts.

    Each announcement is a numbered title row ("N. Title") followed by one detail line per
    rendered row (the bulletin breaks detail lines by hand, so rows are kept as-is). Rows
    before the first numbered item (the column tagline) are skipped. The 봉사자 모집 footer
    sits in bordered boxes below the list, so the scan stops at the first such box.
    """
    footer_top = min(
        (r["top"] for r in page.rects
         if _MID_LEFT <= r["x0"] < _MID_RIGHT and r["x1"] - r["x0"] > 20),
        default=page.height,
    )
    mid_words = [
        w for w in page.extract_words()
        if _MID_LEFT <= w["x0"] < _MID_RIGHT and w["top"] < footer_top
    ]

    rows: dict[int, list] = {}
    for w in mid_words:
        rows.setdefault(round(w["top"]), []).append(w)

    anns: list[dict] = []
    cur: dict | None = None
    for top in sorted(rows):
        text = " ".join(w["text"] for w in sorted(rows[top], key=lambda w: w["x0"])).strip()
        m = re.match(r"^(\d+)\.\s+(.+)", text)
        if m:
            cur = {"number": m.group(1), "title": m.group(2).strip(), "detail": []}
            anns.append(cur)
        elif cur is not None:  # detail row (skip any header text before the first numbered item)
            cur["detail"].append(text)
    return anns


def _announcement_blocks(anns: list[dict]) -> list[str]:
    """Render extracted announcements as slide-ready strings: "N. title" + blank line + detail.

    One string per 교회소식 item, ready for keynote.build.fill_announcement_slides — paragraph 1
    (the numbered title) renders gold and the detail paragraphs render white.
    """
    blocks = []
    for a in anns:
        title = f"{a['number']}. {a['title']}"
        blocks.append(title + ("\n\n" + "\n".join(a["detail"]) if a["detail"] else ""))
    return blocks


def _find_row(worship_order: list[dict], part: str) -> dict:
    """Find a worship-order row by part name, tolerant of spacing and series prefixes.

    The part-name cell sometimes carries a series prefix ("왜 말 씀" for the 말 씀 row, #104),
    so match by whitespace-stripped substring rather than exact equality (mirrors the web UI's
    `pk` predicate). Returns {} when no row matches.
    """
    key = part.replace(" ", "")
    return next((r for r in worship_order if key in r["part"].replace(" ", "")), {})


def announcement_blocks(pdf_path: str) -> list[str]:
    """Per-announcement slide text (title + detail) straight from a bulletin PDF (#16). (pdfplumber)"""
    import pdfplumber

    logging.disable(logging.WARNING)
    try:
        with pdfplumber.open(pdf_path) as pdf:
            return _announcement_blocks(_extract_announcements(pdf.pages[0]))
    finally:
        logging.disable(logging.NOTSET)


# ── Public API ────────────────────────────────────────────────────────────────

def to_iso_date(date: str) -> str:
    """Convert a Korean bulletin date ("2026년 5월 31일") to ISO ("2026-05-31").

    Raises ValueError if no Korean date is found — used to key the per-run store, so a
    bulletin with no detectable date must fail loudly rather than write a junk filename.
    """
    m = re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일", date)
    if not m:
        raise ValueError(f"no Korean date in {date!r}")
    y, mo, d = m.groups()
    return f"{y}-{int(mo):02d}-{int(d):02d}"


def parse(pdf_path: str) -> ServiceData:
    """Parse a bulletin PDF into ServiceData. (pdfplumber)"""
    import pdfplumber

    logging.disable(logging.WARNING)
    try:
        with pdfplumber.open(pdf_path) as pdf:
            text = "".join(p.extract_text() or "" for p in pdf.pages)
            worship_order = _parse_worship_order(pdf.pages[0])
            announcements = _announcement_blocks(_extract_announcements(pdf.pages[0]))
    finally:
        logging.disable(logging.NOTSET)

    date_match = re.search(r"\d{4}년\s*\d{1,2}월\s*\d{1,2}일", text)
    date = re.sub(r"\s+", " ", date_match.group()) if date_match else ""

    call = _find_row(worship_order, "예배의 부름")
    sermon = _find_row(worship_order, "말 씀")
    hymn_no, hymn_title = _parse_offering_hymn(_find_row(worship_order, "봉 헌").get("title", ""))

    return ServiceData(
        date=date,
        worship_order=worship_order,
        announcements=announcements,
        call_to_worship_ref=call.get("ref", ""),
        sermon_title=sermon.get("title", ""),
        sermon_ref=sermon.get("ref", ""),
        offering_hymn_number=hymn_no,
        offering_hymn_title=hymn_title,
    )
