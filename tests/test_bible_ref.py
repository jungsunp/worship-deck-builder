"""Tests for worship_deck.bible.ref — Korean Bible reference parser."""

from __future__ import annotations

import pytest

from worship_deck.bible.ref import BibleRef, _KOREAN_BOOKS, parse_ref


# ---------------------------------------------------------------------------
# Happy-path parsing
# ---------------------------------------------------------------------------

def test_chapter_only() -> None:
    assert parse_ref("시 133") == BibleRef("Psalms", 133, None, None)


def test_verse_range() -> None:
    assert parse_ref("눅 22:14-24") == BibleRef("Luke", 22, 14, 24)


def test_single_verse() -> None:
    assert parse_ref("눅 22:14") == BibleRef("Luke", 22, 14, None)


def test_multi_char_abbreviation() -> None:
    assert parse_ref("고전 13:1-13") == BibleRef("1 Corinthians", 13, 1, 13)


def test_strips_whitespace() -> None:
    assert parse_ref("  시 133  ") == BibleRef("Psalms", 133, None, None)


def test_genesis() -> None:
    assert parse_ref("창 1:1-3") == BibleRef("Genesis", 1, 1, 3)


def test_revelation() -> None:
    assert parse_ref("계 22:21") == BibleRef("Revelation", 22, 21, None)


# ---------------------------------------------------------------------------
# Coverage sanity: all 66 books present and non-empty
# ---------------------------------------------------------------------------

def test_book_count() -> None:
    assert len(_KOREAN_BOOKS) == 66


def test_all_book_values_nonempty() -> None:
    for abbrev, name in _KOREAN_BOOKS.items():
        assert isinstance(name, str) and name, f"Empty name for abbreviation {abbrev!r}"


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

def test_unknown_book_raises() -> None:
    with pytest.raises(ValueError, match="Unknown Korean book abbreviation"):
        parse_ref("Luk 22:14")


def test_no_space_raises() -> None:
    with pytest.raises(ValueError, match="Unrecognizable"):
        parse_ref("눅22:14")


def test_empty_string_raises() -> None:
    with pytest.raises(ValueError, match="Unrecognizable"):
        parse_ref("")


def test_trailing_colon_raises() -> None:
    with pytest.raises(ValueError, match="Unrecognizable"):
        parse_ref("눅 22:")
