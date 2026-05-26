"""Tests for worship_deck.bible.kkrv — 개역한글 lookup from bundled KRV dataset.

All tests are CI-safe: they read from the committed data file; no API key needed.
"""

from __future__ import annotations

import pytest

from worship_deck.bible.ref import BibleRef, parse_ref
from worship_deck.bible.kkrv import fetch_korean


# ---------------------------------------------------------------------------
# Happy-path — content checks
# ---------------------------------------------------------------------------

def test_single_verse() -> None:
    ref = parse_ref("창 1:1")
    text = fetch_korean(ref)
    assert "태초에" in text


def test_verse_range() -> None:
    ref = parse_ref("눅 22:14-24")
    lines = fetch_korean(ref).splitlines()
    assert len(lines) == 11
    assert "유월절" in "\n".join(lines)  # appears in verse 15


def test_chapter_only() -> None:
    ref = parse_ref("시 133")
    lines = fetch_korean(ref).splitlines()
    assert len(lines) == 3   # Psalm 133 has 3 verses


def test_numbered_book_roman_numeral_fix() -> None:
    # 고전 = 1 Corinthians; KorRV.json stores this as "I Corinthians"
    ref = parse_ref("고전 13:1")
    text = fetch_korean(ref)
    assert text  # non-empty — proves the name-fix mapping works


def test_revelation_name_fix() -> None:
    # KorRV.json stores as "Revelation of John"; BibleRef uses "Revelation"
    ref = parse_ref("계 22:21")
    text = fetch_korean(ref)
    assert text


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------

def test_unknown_book_raises() -> None:
    ref = BibleRef("NotABook", 1, 1, None)
    with pytest.raises(ValueError, match="Book not found"):
        fetch_korean(ref)


def test_unknown_chapter_raises() -> None:
    ref = BibleRef("Genesis", 999, 1, None)
    with pytest.raises(ValueError, match="Chapter not found"):
        fetch_korean(ref)


def test_unknown_verse_raises() -> None:
    ref = BibleRef("Genesis", 1, 999, None)
    with pytest.raises(ValueError, match="Verse not found"):
        fetch_korean(ref)
