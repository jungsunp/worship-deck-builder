"""Tests for the bulletin PDF parser."""

from __future__ import annotations

from pathlib import Path

from worship_deck.parse import parse

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_date_from_sample_bulletin() -> None:
    result = parse(str(FIXTURES / "sample_bulletin.pdf"))
    assert result.date == "2026년 5월 17일"
