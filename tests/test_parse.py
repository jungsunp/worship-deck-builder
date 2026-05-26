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


def test_parse_worship_order_songs() -> None:
    result = parse(str(FIXTURES / "sample_bulletin.pdf"))
    songs = [item["song"] for item in result.worship_order]
    assert "마라나타" in songs                      # first worship song
    assert "이를 행하여 나를기념하라" in songs      # sermon title
    assert "피난처 있으니 (찬 70장)" in songs       # offering hymn


def test_parse_worship_order_leaders() -> None:
    result = parse(str(FIXTURES / "sample_bulletin.pdf"))
    by_part: dict[str, list] = {}
    for item in result.worship_order:
        by_part.setdefault(item["part"], []).append(item)
    assert by_part["예배의 부름"][0]["leader"] == "홍길동 목사"
    assert by_part["봉 헌"][0]["leader"] == "다함께"
    assert by_part["말 씀"][0]["leader"] == "홍길동 목사"
