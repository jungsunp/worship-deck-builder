"""Derive section anchors from the template deck's landmark text (#98).

Every section anchor used to be a hard-coded slide index tied to the current
``templates/master.key``; replacing the template silently invalidated them all and the build
edited/deleted the wrong slides. Instead, ``build()`` now dumps every slide's text once
(`keynote.build.dump_slide_texts`, one read-only pass over the open draft) and
``detect_anchors`` locates each section by its stable landmark text — the recurring divider
headings (예배의 부름 / 고백의 찬양 / 사도신경 / 성가대 찬양 / 봉 헌 / 교회 소식), the
[<ref>, 개역한글] verse-label slides, and the 파송의 노래/축도/주기도문 closing.

Fail loud, never guess: a landmark that matches zero or several slides raises RuntimeError
naming the section and the candidate indices, aborting the build before any slide is touched.
``config/slide_map.yaml`` still documents the reference positions for humans.

All indices are 1-based Keynote slide numbers; ``slide_texts[i - 1]`` holds slide i's lines.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Landmark text recurring in every weekly deck. Exact-line matches (the slides carry the
# heading as its own text box); substring matches only where noted.
_PRE_WORSHIP = "기도로 예배 준비해"  # substring: pre-service instruction slide right before 찬양
_CALL_TO_WORSHIP = "예배의 부름"      # + a bracketed ref line, distinguishing it from the banners
_CONFESSION = "고백의 찬양"
_CREED = "사도신경"                   # first slide after the confession song's lyric block
_CHOIR = "성가대 찬양"
_OFFERING = "봉 헌"                   # spaced heading; the hymn-page slides carry plain "봉헌"
_ANNOUNCE_BANNER = "교회 소식"        # banner slides carry ONLY this line
_CLOSING = ("파송의 노래", "축도", "주기도문")  # substring: first one after 말씀 ends the ad-hoc block

_VERSE_LABEL_RE = re.compile(r"^\[.+,\s*개역한글\]$")  # KO label box on every verse-body slide
_BRACKET_RE = re.compile(r"^\[.+\]$")                  # bare bracketed scripture-ref line
_NUMBERED_RE = re.compile(r"^\d+\.")                   # announcement items: "1. <title>"


@dataclass(frozen=True)
class TemplateAnchors:
    """Detected 1-based slide anchors + template section sizes (master.key reference values)."""

    worship_start: int        # 6   찬양 medley range start
    worship_len: int          # 41  medley range length (up to the 예배의 부름 ref slide)
    call_ref: int             # 47  예배의 부름 ref-display slide
    call_verse: int           # 48  예배의 부름 verse-body slide
    call_verse_count: int     # 1   template verse-body slides
    confession_divider: int   # 57  고백의 찬양 divider
    confession_lyric_count: int  # 8   template lyric slides (divider+3 .. 사도신경-2)
    choir_title: int          # 77  성가대 divider (first of 2 title slides)
    choir_lyric_count: int    # 17  template lyric slides (title+2 .. 봉헌-2)
    offering_title: int       # 97  봉헌 native-text title slide
    announcements_start: int  # 117 first numbered 교회소식 item slide
    announcements_count: int  # 5   template item slides
    sermon_ref: int           # 127 말씀 scripture-ref recap slide
    sermon_verse_start: int   # 129 말씀 verse-body block start
    sermon_verse_count: int   # 4   template verse-body slides
    sermon_title: int         # 134 말씀 title slide
    special_start: int        # 135 ad-hoc special block start (#97)
    special_count: int        # 18  ad-hoc slides up to the blank before the closing landmark


def _fail(section: str, detail: str) -> RuntimeError:
    return RuntimeError(
        f"template anchor detection failed — {section}: {detail}. The template deck no longer "
        "matches the expected landmarks (replaced master.key?); fix the deck or the detection "
        f"rules in keynote/anchors.py before building (#98)."
    )


def _unique(section: str, matches: list[int]) -> int:
    if len(matches) != 1:
        raise _fail(section, f"expected exactly one landmark slide, found {matches or 'none'}")
    return matches[0]


def _exact_line(slide_texts: list[list[str]], line: str) -> list[int]:
    return [i for i, lines in enumerate(slide_texts, 1) if line in lines]


def _is_verse_slide(lines: list[str]) -> bool:
    return any(_VERSE_LABEL_RE.match(ln) for ln in lines)


def _run_len(slide_texts: list[list[str]], start: int, pred) -> int:
    """Length of the contiguous run of slides satisfying pred, starting at 1-based `start`."""
    n = 0
    while start + n <= len(slide_texts) and pred(slide_texts[start + n - 1]):
        n += 1
    return n


def detect_anchors(slide_texts: list[list[str]]) -> TemplateAnchors:
    """Locate every section anchor in the dumped deck text. See module docstring.

    Raises:
        RuntimeError: if any landmark is missing, ambiguous, or out of order — the deck
            drifted from the expected structure and a build would edit the wrong slides.
    """
    pre = _unique(
        "찬양 (pre-service instruction)",
        [i for i, lines in enumerate(slide_texts, 1) if any(_PRE_WORSHIP in ln for ln in lines)],
    )
    worship_start = pre + 1

    call_ref = _unique(
        "예배의 부름 (ref slide)",
        [
            i
            for i, lines in enumerate(slide_texts, 1)
            if _CALL_TO_WORSHIP in lines and any(ln.startswith("[") for ln in lines)
        ],
    )
    worship_len = call_ref - worship_start
    call_verse = call_ref + 1
    call_verse_count = _run_len(slide_texts, call_verse, _is_verse_slide)
    if call_verse_count < 1:
        raise _fail("예배의 부름 (verse slide)", f"slide {call_verse} carries no 개역한글 label")

    confession_divider = _unique("고백의 찬양 (divider)", _exact_line(slide_texts, _CONFESSION))
    creed = _unique(
        "사도신경 (confession-section end)",
        [i for i in _exact_line(slide_texts, _CREED) if i > confession_divider],
    )
    # divider + blank + title banner precede the lyrics; a trailing blank precedes 사도신경.
    confession_lyric_count = creed - confession_divider - 4

    choir_title = _unique("성가대 찬양 (divider)", _exact_line(slide_texts, _CHOIR))
    offering_title = _unique("봉헌 (title slide)", _exact_line(slide_texts, _OFFERING))
    # two title slides precede the lyrics; a trailing blank precedes the 봉헌 title.
    choir_lyric_count = offering_title - choir_title - 3

    banners = [i for i, lines in enumerate(slide_texts, 1) if lines == [_ANNOUNCE_BANNER]]
    if not banners:
        raise _fail("교회소식 (banner)", "no slide carries only the 교회 소식 banner line")
    verse_after_banner = [
        i for i, lines in enumerate(slide_texts, 1) if i > banners[-1] and _is_verse_slide(lines)
    ]
    if not verse_after_banner:
        raise _fail("말씀 (verse block)", "no 개역한글-labelled slide after the 교회소식 banners")
    sermon_verse_start = verse_after_banner[0]

    numbered = [
        i
        for i, lines in enumerate(slide_texts, 1)
        if banners[-1] < i < sermon_verse_start and lines and _NUMBERED_RE.match(lines[0])
    ]
    if not numbered:
        raise _fail("교회소식 (item slides)", "no numbered item slide after the 교회 소식 banners")
    announcements_start = numbered[0]
    announcements_count = _run_len(
        slide_texts, announcements_start, lambda lines: bool(lines) and bool(_NUMBERED_RE.match(lines[0]))
    )

    sermon_verse_count = _run_len(slide_texts, sermon_verse_start, _is_verse_slide)
    sermon_ref = _unique(
        "말씀 (ref recap slide)",
        [
            i
            for i, lines in enumerate(slide_texts, 1)
            if announcements_start + announcements_count <= i < sermon_verse_start
            and any(_BRACKET_RE.match(ln) for ln in lines)
        ],
    )

    verse_end = sermon_verse_start + sermon_verse_count - 1
    sermon_title = next(
        (
            i
            for i, lines in enumerate(slide_texts, 1)
            if i > verse_end
            and not _is_verse_slide(lines)
            and any(_BRACKET_RE.match(ln) for ln in lines)
        ),
        0,
    )
    if not sermon_title:
        raise _fail("말씀 (title slide)", f"no bracketed-ref title slide after slide {verse_end}")

    closing = next(
        (
            i
            for i, lines in enumerate(slide_texts, 1)
            if i > sermon_title and any(mark in ln for ln in lines for mark in _CLOSING)
        ),
        0,
    )
    if not closing:
        raise _fail("말씀 (closing landmark)", "no 파송의 노래/축도/주기도문 slide after the 말씀 title")
    # Drop everything between the 말씀 title and the blank-green separator that precedes the
    # closing landmark (mirrors the template's structure; the separator slide is kept).
    special_start = sermon_title + 1
    special_count = closing - special_start - 1

    anchors = TemplateAnchors(
        worship_start=worship_start,
        worship_len=worship_len,
        call_ref=call_ref,
        call_verse=call_verse,
        call_verse_count=call_verse_count,
        confession_divider=confession_divider,
        confession_lyric_count=confession_lyric_count,
        choir_title=choir_title,
        choir_lyric_count=choir_lyric_count,
        offering_title=offering_title,
        announcements_start=announcements_start,
        announcements_count=announcements_count,
        sermon_ref=sermon_ref,
        sermon_verse_start=sermon_verse_start,
        sermon_verse_count=sermon_verse_count,
        sermon_title=sermon_title,
        special_start=special_start,
        special_count=special_count,
    )

    order = [
        anchors.worship_start,
        anchors.call_ref,
        anchors.call_verse,
        anchors.confession_divider,
        creed,
        anchors.choir_title,
        anchors.offering_title,
        anchors.announcements_start,
        anchors.sermon_ref,
        anchors.sermon_verse_start,
        anchors.sermon_title,
        closing,
    ]
    if order != sorted(order) or min(
        worship_len, confession_lyric_count, choir_lyric_count, special_count + 1
    ) < 1:
        raise _fail("section order", f"detected anchors are out of order or empty: {anchors}")
    return anchors
