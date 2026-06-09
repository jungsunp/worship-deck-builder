"""Tests for the bulletin PDF parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from worship_deck.parse import parse
from worship_deck.parse.bulletin import (
    _find_row,
    _parse_offering_hymn,
    _part_cell,
    _split_content,
    announcement_blocks,
)


def _w(text: str, x0: float, x1: float) -> dict:
    return {"text": text, "x0": x0, "x1": x1}

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_date_from_sample_bulletin() -> None:
    result = parse(str(FIXTURES / "sample_bulletin.pdf"))
    assert result.date == "2026년 5월 17일"


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
    # The opening 찬양 row's content (마라나타) is the worship BAND NAME, not a song.
    # The bulletin lists no opening-worship song titles — those come from the band
    # sheet and land in the top-level worship_songs field at assemble time.
    opening = next(r for r in result.worship_order if r["part"] == "찬 양")
    assert opening["title"] == "마라나타"  # band name, surfaced as content — not a worship song


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
    assert by_part["봉 헌"][0]["leader"] == "다함께"
    assert by_part["말 씀"][0]["leader"] == "홍길동 목사"
