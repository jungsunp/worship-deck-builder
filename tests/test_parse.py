"""Tests for the bulletin PDF parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from worship_deck.parse import parse
from worship_deck.parse.bulletin import (
    _parse_offering_hymn,
    _split_content,
    announcement_blocks,
)

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
    assert "이를 행하여 나를기념하라" in titles      # sermon title
    assert "피난처 있으니 (찬 70장)" in titles       # offering hymn
    # The opening 찬양 row's content (마라나타) is the worship BAND NAME, not a song.
    # The bulletin lists no opening-worship song titles — those come from the band
    # sheet and are attached to the slot by lyrics.match.assign_worship_songs.
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


def test_parse_announcements_titles() -> None:
    result = parse(str(FIXTURES / "sample_bulletin.pdf"))
    assert result.announcements[0] == "2026년도 24 나무 소그룹"
    assert result.announcements[1] == "교육부 오픈하우스 안내"
    assert result.announcements[5] == "미디어 사역팀 팀원 모집"


def test_announcement_blocks_title_and_reflowed_detail() -> None:
    blocks = announcement_blocks(str(FIXTURES / "sample_bulletin.pdf"))
    assert len(blocks) == 6

    first = blocks[0]
    lines = first.split("\n")
    assert lines[0] == "1. 2026년도 24 나무 소그룹"  # title keeps its number (paragraph 1 = gold)
    assert lines[1] == ""  # blank line between title and detail
    # the soft column-wrap "...안내에 따" / "라 함께..." is rejoined into one flowing line
    assert "안내에 따라 함께 친교해 주시기 바랍니다." in first
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
    assert result.sermon_ref == "눅 22:14-24"
    assert result.sermon_title == "이를 행하여 나를기념하라"


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


def test_parse_worship_order_leaders() -> None:
    result = parse(str(FIXTURES / "sample_bulletin.pdf"))
    by_part: dict[str, list] = {}
    for item in result.worship_order:
        by_part.setdefault(item["part"], []).append(item)
    assert by_part["예배의 부름"][0]["leader"] == "홍길동 목사"
    assert by_part["봉 헌"][0]["leader"] == "다함께"
    assert by_part["말 씀"][0]["leader"] == "홍길동 목사"
