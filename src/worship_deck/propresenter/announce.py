"""교회 소식 item text → the parts the 라벨 레일 plate lays out (#233).

An announcement reaches the generator as one string — ``"6. 다니엘 지상사 한국학교 개강 안내"``,
a blank line, then the bulletin's detail paragraphs. The old plate printed that verbatim, a gold
title over a muted prose block, and measured across the 112 items in the 14 weeks of
``data/runs`` it filled a **median of 54%** of its box while 4 items overflowed and had to be
shrunk. So the plate was built for a worst case that happens 4% of the time and looked half-empty
the rest.

This lifts the *answerable* facts out of the prose — 날짜 / 시간 / 장소 / 문의 … — into rows the
plate sets as a two-column rail, and leaves the rest as prose. The lifting is deliberately
shallow: regexes over the shapes the bulletin actually writes, not an attempt to understand the
sentence. Five rules decide it, in this order, and nothing else does:

1. **Any line the bulletin already wrote as ``라벨: 값``** becomes a row — with or without a
   bullet in front (``•``, ``·``, ``-``, ``*`` are all used, sometimes within one notice), and
   with a qualifying parenthetical moved to the head of the value so the label column stays a
   column (``영유아부(30개월-K): 8/3``).
2. **A wrapped line continues the row above it** when both are comma-runs with no sentence
   punctuation — the bulletin breaks a long roster wherever its column ran out.
3. **A bare roster of Korean names**, captioned by nobody, becomes a row with an *empty* label,
   so the operator can name it in review by typing one word into the block text.
4. **``(문의: …)``** is pulled out wherever it sits — inside a sentence or trailing another
   row's value — and is always the last row.
5. **A leading date, and a time right behind it,** are lifted off the front of the first
   sentence; a date the sentence is built *around* (``6/14부터 6/21까지…``) is left alone,
   because lifting it would leave the sentence starting on a dangling particle.

Everything else stays prose, in the order the bulletin wrote it. Across the 14 weeks in
``data/runs``, that gives every notice but a handful at least one row, and the operator can force
any fact onto the rail by writing it as ``라벨: 값`` in the review editor.

It runs at *build* time rather than in ``parse.bulletin`` because the review editor hands these
same strings back after the operator edits them, and ``keynote.build`` consumes them unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# A parenthetical that qualifies a date — "(주일)", "(목요일)", "(14주)", "(오늘)" — but not one
# that is really a time, "(오전 6시 출발)", which belongs in the 시간 row instead.
_QUALIFIER = r"\((?![^)]*(?:\d\s*시|\d:\d))[^)]{1,10}\)"
_MD = r"\d{1,2}/\d{1,2}(?:/\d{2,4})?"
_ONE_DATE = rf"{_MD}\s*(?:{_QUALIFIER})?"
# The bulletin writes its ranges with a soft hyphen (U+00AD) about as often as a real dash.
_RANGE = "\\s*[-–—~\u00ad]\\s*"
_DATE = re.compile(rf"^({_ONE_DATE}(?:{_RANGE}{_ONE_DATE})?)")

_CLOCK = r"\d{1,2}:\d{2}"
_KCLOCK = r"(?:오전|오후)\s*\d{1,2}(?::\d{2})?시?"
_ONE_TIME = rf"(?:{_CLOCK}|{_KCLOCK})"
# "주일 1:20~3:50", "1:15 PM", "3:00-3:30 PM", "오전 6시" — the day word is kept because
# "1:20" on its own would lose which day the 14-week class actually meets.
_TIME = re.compile(
    rf"^((?:주일|평일|매주|매일)?\s*{_ONE_TIME}(?:{_RANGE}{_ONE_TIME})?(?:\s*[APap]\.?[Mm]\.?)?)"
)
# The same thing written as a parenthetical right after the date: "(오전 6시 출발)".
_PAREN_TIME = re.compile(r"^\(([^)\n]{0,24}?(?:\d\s*시|\d:\d\d)[^)\n]{0,10})\)")

# "•장소: 레익뷰 언약교회", "- 일시: 9월중 1박2일", "대상자: …", "영유아부(30개월-K): …" — the
# bulletin's own key/value lines. Every bullet glyph it has used counts (it writes •, ·, - and *
# interchangeably from week to week), and a parenthetical qualifying the label is moved to the
# front of the value so the label column stays a column.
_BULLET = r"[•·∙*\-–—]"
_LABEL = re.compile(
    rf"^\s*(?:{_BULLET}\s*)?([가-힣][가-힣\s]{{0,6}})\s*(\([^)\n]{{1,30}}\))?\s*[:：]\s*(\S.*?)\s*$"
)
_CONTACT = re.compile(r"\(\s*문의\s*[:：]\s*([^)\n]+?)\s*\)")

# A line the bulletin wraps rather than ends: a comma-separated run with no sentence-ending
# punctuation, which is how it writes every roster ("한진규/정양은, 전재영/박샤론,").
_LISTY = re.compile(r"^[^.。!?]*[,，][^.。!?]*$")
# …and the subset of those that is a bare roster of Korean names, with no label in front of it.
_NAME = r"[가-힣]{2,4}(?:\s*/\s*[가-힣]{2,4})*"
_NAME_LIST = re.compile(rf"^\(?\s*{_NAME}(?:\s*,\s*{_NAME})+\s*(?:\([^)]*\))?\s*\)?$")
# A date the sentence is built around — "6/14 (주일)부터 6/21 (주일)까지" — must stay in the
# prose: lifting it into the rail leaves the sentence starting on a dangling particle.
_PARTICLE = re.compile(
    r"^(?:(?:부터|까지|에|은|는|이|가|의|와|과|도|로|을|를)|\s+(?:부터|까지)(?=\s|$))"
)
_LEAD_JUNK = re.compile(r"^[\s,.·、]+")


@dataclass(frozen=True)
class Item:
    """One 교회 소식 notice, ready to lay out. ``rows`` is the rail, in reading order:
    날짜/시간 first, the bulletin's own labels next, 문의 last."""

    title: str
    rows: tuple[tuple[str, str], ...] = ()
    paragraphs: tuple[str, ...] = ()


def _tidy(text: str) -> str:
    """Normalise a lifted value: soft hyphens become en dashes, runs of space collapse."""
    return re.sub(r"\s+", " ", text.replace("\u00ad", "–")).strip()


def _continues(value: str, line: str) -> bool:
    """Is ``line`` the tail of the previous rail value, wrapped onto its own line?

    The bulletin breaks a long roster wherever the column ran out — "…두성원/두경민," then
    "이유은, 리사김" on the next line — so the second line belongs to the row above, not to the
    prose. Only a comma-run following a comma-run qualifies; a sentence never does.
    """
    return bool(_LISTY.match(line)) and (value.endswith(",") or bool(_LISTY.match(value)))


def _unwrap(text: str) -> str:
    """Drop one wrapping paren pair — the bulletin parenthesises whole rosters."""
    return text[1:-1].strip() if text.startswith("(") and text.endswith(")") else text


def _lift_roster(lines: list[str]) -> tuple[list[str], str | None]:
    """Split a paragraph's trailing bare name roster off from its prose.

    A list of names that is nobody's answer to a question — no 대상자: in front of it — still
    reads as a rail row rather than as a sentence, and putting it there lets the operator add
    the label in review by typing one word into the block text.
    """
    end = len(lines)
    while end and _LISTY.match(lines[end - 1]):
        end -= 1
    roster = " ".join(lines[end:])
    if end == len(lines) or not _NAME_LIST.match(roster):
        return lines, None
    return lines[:end], _unwrap(_tidy(roster))


def parse_item(block: str) -> Item:
    """Split one ``"N. title\\n\\ndetail"`` block into its title, rail rows and prose."""
    head, _, detail = block.partition("\n\n")
    title = re.sub(r"^\s*\d+\.\s*", "", head).strip()

    labelled: list[list[str]] = []
    contact: list[list[str]] = []
    paragraphs: list[str] = []
    for para in detail.split("\n\n"):
        kept: list[str] = []
        open_row: list[str] | None = None
        for line in para.split("\n"):
            m = _LABEL.match(line)
            if m:
                label = _tidy(m.group(1))
                open_row = [label, _tidy(f"{m.group(2) or ''} {m.group(3)}")]
                (contact if label == "문의" else labelled).append(open_row)
                continue
            line = line.strip()
            if open_row and line and _continues(open_row[1], line):
                sep = "" if open_row[1].endswith(",") else ","
                open_row[1] = _tidy(f"{open_row[1]}{sep} {line}")
                continue
            open_row = None
            if line:
                kept.append(line)
        kept, roster = _lift_roster(kept)
        if roster:
            labelled.append(["", roster])
        if kept:
            paragraphs.append("\n".join(kept))

    # "(문의: 안명철 집사)" is written inline at the end of a sentence — or of a rail value — far
    # more often than on a line of its own, so it is pulled out rather than matched as a label.
    for row in labelled:
        m = _CONTACT.search(row[1])
        if m:
            contact.append(["문의", _tidy(m.group(1))])
            row[1] = _tidy(_CONTACT.sub("", row[1]))
    text = "\n\n".join(paragraphs)
    m = _CONTACT.search(text)
    if m:
        contact.append(["문의", _tidy(m.group(1))])
        text = _CONTACT.sub("", text)
    paragraphs = [p for p in (q.strip() for q in text.split("\n\n")) if p]

    dated: list[tuple[str, str]] = []
    if paragraphs:
        first, _, rest = paragraphs[0].partition("\n")
        d = _DATE.match(first)
        if d and not _PARTICLE.match(first[d.end():]):
            dated.append(("날짜", _tidy(d.group(1))))
            first = first[d.end():].lstrip()
            t = _PAREN_TIME.match(first) or _TIME.match(first)
            if t and not _PARTICLE.match(first[t.end():]):
                dated.append(("시간", _tidy(t.group(1))))
                first = first[t.end():]
            # Lifting the date off the front leaves ", 온세기 예배로 모입니다." — a sentence that
            # now starts on its own punctuation.
            first = _LEAD_JUNK.sub("", first)
            paragraphs[0] = "\n".join(p for p in (first, rest) if p.strip()).strip()
            paragraphs = [p for p in paragraphs if p]

    rows = dated + [(label, value) for label, value in labelled + contact]
    return Item(title, tuple(rows), tuple(paragraphs))
