"""Tests for the bulletin PDF parser."""

from __future__ import annotations

from pathlib import Path

from worship_deck.parse import parse

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
    assert "마라나타" in titles                      # first worship song
    assert "이를 행하여 나를기념하라" in titles      # sermon title
    assert "피난처 있으니 (찬 70장)" in titles       # offering hymn


def test_parse_announcements_count() -> None:
    result = parse(str(FIXTURES / "sample_bulletin.pdf"))
    assert len(result.announcements) == 6


def test_parse_announcements_titles() -> None:
    result = parse(str(FIXTURES / "sample_bulletin.pdf"))
    assert result.announcements[0] == "2026년도 24 나무 소그룹"
    assert result.announcements[1] == "교육부 오픈하우스 안내"
    assert result.announcements[5] == "미디어 사역팀 팀원 모집"


def test_parse_worship_order_leaders() -> None:
    result = parse(str(FIXTURES / "sample_bulletin.pdf"))
    by_part: dict[str, list] = {}
    for item in result.worship_order:
        by_part.setdefault(item["part"], []).append(item)
    assert by_part["예배의 부름"][0]["leader"] == "홍길동 목사"
    assert by_part["봉 헌"][0]["leader"] == "다함께"
    assert by_part["말 씀"][0]["leader"] == "홍길동 목사"
