"""Tests for the bulletin PDF parser."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from worship_deck.parse import parse
from worship_deck.parse.bulletin import (
    _announcement_blocks,
    _expand_list_paren,
    _extract_announcements,
    _find_row,
    _masthead_date,
    _parse_offering_hymn,
    _part_cell,
    _split_content,
    _split_performer,
    announcement_blocks,
)


def _w(text: str, x0: float, x1: float) -> dict:
    return {"text": text, "x0": x0, "x1": x1}


def _mw(text: str, top: float, x0: float = 350.0) -> dict:
    """A middle-column (교회소식) word at a given top/x0."""
    return {"text": text, "x0": x0, "x1": x0 + 10, "top": top}


class _FakePage:
    def __init__(self, words: list[dict], height: float = 1000.0) -> None:
        self._words = words
        self.rects: list[dict] = []  # no footer boxes → scan whole column
        self.height = height

    def extract_words(self) -> list[dict]:
        return self._words


def test_extract_announcements_keeps_same_line_tail_with_its_own_item() -> None:
    """A numbered title whose inline sentence is jittered 1px stays whole and splits on ' - '.

    Mirrors the bulletin's '3. 임직식 - 6/28 … 있습니다.' written as one visual line: the tail
    sits 1px above the title, so naive top-bucketing would dump it on the previous item.
    """
    words = [
        _mw("2.", 150), _mw("청년부", 150, x0=362),  # ann 2 title
        _mw("성경통독", 160),  # ann 2 detail
        _mw("3.", 212), _mw("임직식", 212, x0=362), _mw("-", 212, x0=382),
        _mw("6/28", 211, x0=400), _mw("있습니다.", 211, x0=420),  # tail, 1px above the title
        _mw("(피택", 222),  # ann 3 detail
    ]
    anns = _extract_announcements(_FakePage(words))
    by_num = {a["number"]: a for a in anns}
    # the sentence belongs to ann 3, not ann 2
    assert "있습니다." not in " ".join(by_num["2"]["detail"])
    assert by_num["3"]["title"] == "임직식"
    assert by_num["3"]["detail"][0] == "6/28 있습니다."
    assert "(피택" in by_num["3"]["detail"][1]

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_date_from_sample_bulletin() -> None:
    result = parse(str(FIXTURES / "sample_bulletin.pdf"))
    assert result.date == "2026년 5월 17일"


def test_masthead_date_ignores_stray_body_dates() -> None:
    # The masthead "N권 M호 / YYYY년 M월 D일" is authoritative; an obituary date elsewhere on
    # the page must not win. extract_words() returns dicts with text/top/bottom/x0.
    page = SimpleNamespace(
        extract_words=lambda: [
            {"text": "2026년", "top": 10, "bottom": 20, "x0": 5},  # obituary, wrong date
            {"text": "6월", "top": 10, "bottom": 20, "x0": 40},
            {"text": "21일", "top": 10, "bottom": 20, "x0": 70},
            {"text": "31권", "top": 40, "bottom": 50, "x0": 699},  # masthead issue line
            {"text": "26호", "top": 40, "bottom": 50, "x0": 725},
            {"text": "2026년", "top": 60, "bottom": 70, "x0": 700},  # service date, below it
            {"text": "6월", "top": 60, "bottom": 70, "x0": 742},
            {"text": "28일", "top": 60, "bottom": 70, "x0": 764},
        ]
    )
    assert _masthead_date(page) == "2026년 6월 28일"


def test_masthead_date_returns_empty_when_no_issue_line() -> None:
    page = SimpleNamespace(extract_words=lambda: [{"text": "2026년", "top": 10, "bottom": 20, "x0": 5}])
    assert _masthead_date(page) == ""


def test_parse_worship_order_has_all_parts() -> None:
    result = parse(str(FIXTURES / "sample_bulletin.pdf"))
    parts = [item["part"] for item in result.worship_order]
    assert len(result.worship_order) == 12
    for expected in ("찬 양", "예배의 부름", "봉 헌", "말 씀"):
        assert expected in parts


def test_parse_worship_order_titles() -> None:
    result = parse(str(FIXTURES / "sample_bulletin.pdf"))
    titles = [item["title"] for item in result.worship_order]
    assert "설득된 믿음" in titles                   # sermon title
    assert "피난처 있으니 (찬 70장)" in titles       # offering hymn
    # 마라나타 is the worship BAND NAME — a performer, not a song title. It sits in the right
    # performer sub-column, so it parses as the row's leader and the title stays empty. The
    # bulletin lists no opening-worship song titles — those come from the band sheet and
    # land in the top-level worship_songs field at assemble time.
    opening = next(r for r in result.worship_order if r["part"] == "찬 양")
    assert opening["title"] == ""
    assert opening["leader"] == "마라나타"


def test_parse_offering_hymn_from_sample_bulletin() -> None:
    result = parse(str(FIXTURES / "sample_bulletin.pdf"))
    assert result.offering_hymn_number == "70"
    assert result.offering_hymn_title == "피난처 있으니"
    assert result.offering_hymn_verses == []  # not in bulletin → all verses


def test_parse_announcements_count() -> None:
    result = parse(str(FIXTURES / "sample_bulletin.pdf"))
    assert len(result.announcements) == 6


def test_parse_announcements_blocks() -> None:
    """announcements now hold full slide blocks (numbered title + detail), not bare titles."""
    result = parse(str(FIXTURES / "sample_bulletin.pdf"))
    # paragraph 1 (gold title) keeps its number; detail follows after a blank line
    assert result.announcements[0].split("\n")[0] == "1. 2026년도 24 나무 소그룹"
    assert result.announcements[1].split("\n")[0] == "2. 교육부 오픈하우스 안내"
    assert result.announcements[5].split("\n")[0] == "6. 미디어 사역팀 팀원 모집"
    # the detail lines that build() renders white must survive into the run store
    assert "그룹 리더분들의 안내에 따라 함께 친교해 주시기 바랍니다." in result.announcements[0]


def test_announcement_blocks_title_and_detail() -> None:
    blocks = announcement_blocks(str(FIXTURES / "sample_bulletin.pdf"))
    assert len(blocks) == 6

    first = blocks[0]
    lines = first.split("\n")
    assert lines[0] == "1. 2026년도 24 나무 소그룹"  # title keeps its number (paragraph 1 = gold)
    assert lines[1] == ""  # blank line between title and detail
    # each rendered row is kept as its own detail line (the bulletin breaks lines by hand)
    assert "그룹 리더분들의 안내에 따라 함께 친교해 주시기 바랍니다." in lines
    assert "  " not in first  # no stray leading/double spacing from pdf wrapping


def test_announcement_blocks_keeps_bullets_as_separate_lines() -> None:
    blocks = announcement_blocks(str(FIXTURES / "sample_bulletin.pdf"))
    vbs = blocks[4]  # 5. 노스필드 여름성경학교 (VBS) 안내
    detail = vbs.split("\n\n", 1)[1].split("\n")
    assert "· 영유아부: 8/3-8/4 (월-화) 9am-12pm" in detail
    assert "· 초등부: 8/5-8/7 (수-금) 9am-3pm" in detail


def test_expand_list_paren_splits_korean_label_list() -> None:
    line = "(피택 시무장로: 손성호, 피택 안수집사: 범시훈, 피택시무권사: 김현진, 이옥례)"
    assert _expand_list_paren(line) == [
        "· 피택 시무장로: 손성호",
        "· 피택 안수집사: 범시훈",
        "· 피택시무권사: 김현진, 이옥례",
    ]


def test_expand_list_paren_leaves_prose_unchanged() -> None:
    assert _expand_list_paren("그룹 리더분들의 안내에 따라.") == ["그룹 리더분들의 안내에 따라."]
    # bullet line with mid-word paren: not a whole-line paren, must be left alone
    assert _expand_list_paren("· 영유아부: 8/3-8/4 (월-화) 9am-12pm") == [
        "· 영유아부: 8/3-8/4 (월-화) 9am-12pm"
    ]
    # paren with commas but no colons → no split
    assert _expand_list_paren("(단독 설명, 괄호만)") == ["(단독 설명, 괄호만)"]
    # only one label:value item → fewer than 2 parts → no split
    assert _expand_list_paren("(피택 시무장로: 손성호)") == ["(피택 시무장로: 손성호)"]


def test_announcement_blocks_expands_list_paren() -> None:
    anns = [{"number": "3", "title": "임직식", "detail": [
        "(피택 시무장로: 손성호, 피택 안수집사: 범시훈, 피택시무권사: 김현진, 이옥례)"
    ]}]
    block = _announcement_blocks(anns)[0]
    lines = block.split("\n")
    assert lines[0] == "3. 임직식"
    assert lines[1] == ""
    assert "· 피택 시무장로: 손성호" in lines
    assert "· 피택 안수집사: 범시훈" in lines
    assert "· 피택시무권사: 김현진, 이옥례" in lines


def test_parse_bible_refs_and_sermon_title() -> None:
    result = parse(str(FIXTURES / "sample_bulletin.pdf"))
    assert result.call_to_worship_ref == "시 133:1-3"
    # sermon ref uses a full Korean book name ("요한복음"), which the parser must also strip
    assert result.sermon_ref == "요한복음 4:43-54"
    assert result.sermon_title == "설득된 믿음"


# ── _split_content() unit tests ───────────────────────────────────────────────
# Direct branch coverage the single fixture can't exercise: each shape appears
# only once in sample_bulletin.pdf, so these probe the helper in isolation.

@pytest.mark.parametrize(
    ("content", "expected"),
    [
        # Inline ref at start → no title, remainder is leader, ref captured
        ("시 133:1-3 홍길동 목사", ("", "홍길동 목사", "시 133:1-3")),
        ("시 133 다함께", ("", "다함께", "시 133")),
        # Parenthesized ref mid-line → title kept, ref stripped + captured
        ("이를 행하여 나를기념하라 (눅 22:14-24) 홍길동 목사",
         ("이를 행하여 나를기념하라", "홍길동 목사", "눅 22:14-24")),
        # Leader token at end, no ref
        ("사도신경 다함께", ("사도신경", "다함께", "")),
        # Title-suffix leader (목사/전도사/…) peeled as two tokens
        ("축도 홍길동 목사", ("축도", "홍길동 목사", "")),
        ("말씀 김철수 전도사", ("말씀", "김철수 전도사", "")),
        # Plain title, no leader and no ref
        ("주기도문", ("주기도문", "", "")),
        # Hymn number (찬 N장) is NOT a Bible book → left in the title
        ("피난처 있으니 (찬 70장) 다함께", ("피난처 있으니 (찬 70장)", "다함께", "")),
        # Empty / whitespace-only content
        ("", ("", "", "")),
        ("   ", ("", "", "")),
    ],
)
def test_split_content_branches(content: str, expected: tuple[str, str, str]) -> None:
    assert _split_content(content) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        # Sample-bulletin shape: title first, number in parens with 장
        ("피난처 있으니 (찬 70장)", ("70", "피난처 있으니")),
        # Alternate shape: 찬N. prefix, then title
        ("찬220. 사랑하는 주님 앞에", ("220", "사랑하는 주님 앞에")),
        # No hymn number → number blank, title preserved
        ("주님 곁으로", ("", "주님 곁으로")),
        # Empty content
        ("", ("", "")),
    ],
)
def test_parse_offering_hymn_branches(title: str, expected: tuple) -> None:
    assert _parse_offering_hymn(title) == expected


# ── _part_cell() unit tests ───────────────────────────────────────────────────
# Real coords from NPC060726: the 말 씀 row carries a gutter series prefix "왜" (x0≈97)
# between the part name (x≈27–47) and the content; it must split off into the content (it
# leads the sermon title "왜 그럼 그 때는…"), not glue onto the part name (#104).

def test_part_cell_splits_gutter_series_prefix_to_content() -> None:
    # 말(27–36) 씀(39–47)  …50pt gap…  왜(97–104)
    cells = [_w("말", 27.4, 36.1), _w("씀", 38.7, 47.3), _w("왜", 97.3, 104.2)]
    assert _part_cell(cells) == ("말 씀", ["왜"])


def test_part_cell_keeps_multi_word_part_and_strips_footnote() -> None:
    # 환영(27–45) 및(47–56) 인사*(59–80) — small gaps, all one part; trailing * stripped, no gutter
    cells = [_w("환영", 27, 45), _w("및", 47, 56), _w("인사*", 59, 80)]
    assert _part_cell(cells) == ("환영 및 인사", [])


def test_part_cell_empty() -> None:
    assert _part_cell([]) == ("", [])


# ── _split_performer() unit tests ─────────────────────────────────────────────
# Real coords from the 6/21 bulletin (data/inbox/bulletin.pdf). The performer sits in a
# right sub-column; _split_performer separates it by x-position, so it is immune to the
# sub-pt baseline jitter that scrambled the old (top, x0) flatten order (#142), and works
# for any performer label — clergy, congregation, or an unknown ensemble.

def _texts(words: list[dict]) -> list[str]:
    return [w["text"] for w in words]


def test_split_performer_clergy_after_gap() -> None:
    # Sermon row: pastor sub-column (x≈272) sits after a wide gap; input order scrambled
    # (clergy first, as the buggy baseline-sort flattened it) — the x-sort still separates it.
    words = [
        _w("강선우", 271.6, 293.4), _w("목사", 295.2, 309.8),
        _w("영적", 130.8, 144.6), _w("아버지", 146.7, 167.4),
        _w("(삼상", 169.0, 188.0), _w("7:3-14)", 189.0, 205.0),
    ]
    title, perf = _split_performer(words)
    assert _texts(title) == ["영적", "아버지", "(삼상", "7:3-14)"]
    assert _texts(perf) == ["강선우", "목사"]


def test_split_performer_ensemble_after_gap() -> None:
    # 봉 헌 row: the choir's 남성 중창(단) ensemble trails the title past the column gap.
    words = [
        _w("주하나님", 116.7, 143.7), _w("지으신", 145.4, 165.8), _w("세계", 182.8, 196.5),
        _w("(찬", 198.0, 207.0), _w("79장)", 209.1, 226.4),
        _w("성가대", 255.2, 277.0), _w("남성", 278.8, 293.4), _w("중창", 295.2, 309.8),
    ]
    title, perf = _split_performer(words)
    assert _texts(title) == ["주하나님", "지으신", "세계", "(찬", "79장)"]
    assert _texts(perf) == ["성가대", "남성", "중창"]


def test_split_performer_lone_band_name_is_performer() -> None:
    # The opening 찬양 carries only the worship BAND NAME (마라나타 at x≈281, the performer
    # sub-column) and no song title → all performer, no title (#142 follow-up).
    title, perf = _split_performer([_w("마라나타", 281.0, 309.8)])
    assert title == []
    assert _texts(perf) == ["마라나타"]


def test_split_performer_no_gap_performer_only_is_performer() -> None:
    # Performer-only row (교회소식/축도): the whole run sits in the performer sub-column
    # (x0 ≥ _LEADER_X) with no preceding title → all performer, no title.
    words = [_w("강선우", 271.6, 293.4), _w("목사", 295.2, 309.8)]
    title, perf = _split_performer(words)
    assert title == []
    assert _texts(perf) == ["강선우", "목사"]


# ── _find_row() unit tests ────────────────────────────────────────────────────
# The sermon row sometimes carries a series prefix in the part cell ("왜 말 씀"); the
# lookup must match by whitespace-stripped substring, not exact equality (#104).

def test_find_row_matches_series_prefix() -> None:
    order = [
        {"part": "예배의 부름", "title": "", "leader": "", "ref": "시 133:1-3"},
        {"part": "왜 말 씀", "title": "그럼 그 때는", "leader": "강선우 목사", "ref": "삼상 5:1-12"},
        {"part": "봉 헌", "title": "피난처 있으니 (찬 70장)", "leader": "다함께", "ref": ""},
    ]
    assert _find_row(order, "말 씀")["title"] == "그럼 그 때는"
    assert _find_row(order, "말 씀")["ref"] == "삼상 5:1-12"
    # exact-spacing rows still match
    assert _find_row(order, "예배의 부름")["ref"] == "시 133:1-3"
    assert _find_row(order, "봉 헌")["title"] == "피난처 있으니 (찬 70장)"
    # no match → {}
    assert _find_row(order, "축 도") == {}


def test_parse_worship_order_leaders() -> None:
    result = parse(str(FIXTURES / "sample_bulletin.pdf"))
    by_part: dict[str, list] = {}
    for item in result.worship_order:
        by_part.setdefault(item["part"], []).append(item)
    assert by_part["예배의 부름"][0]["leader"] == "홍길동 목사"
    # 봉 헌 is sung by 남성 중창단 — an ensemble label in no token vocabulary; it is separated
    # by its right-column x-position (not by matching a word), proving _split_performer (#142).
    assert by_part["봉 헌"][0]["leader"] == "남성 중창단"
    assert by_part["말 씀"][0]["leader"] == "홍길동 목사"
    # opening 찬 양: the band name 마라나타 is the performer, not a song title (no title here)
    assert by_part["찬 양"][0]["leader"] == "마라나타"
