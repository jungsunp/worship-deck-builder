"""Tests for worship_deck.bible.ref — Korean Bible reference parser."""

from __future__ import annotations

import pytest

from worship_deck.bible.ref import (
    _KOREAN_BOOKS,
    _KOREAN_FULL_BOOKS,
    BibleRef,
    korean_ref,
    parse_ref,
)

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
# Coverage sanity: all 66 books present and non-empty, in both abbreviated and
# full-name forms (132 entries) — bulletins use either.
# ---------------------------------------------------------------------------

def test_book_count() -> None:
    assert len(_KOREAN_BOOKS) == 132
    assert len(set(_KOREAN_BOOKS.values())) == 66


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


# ---------------------------------------------------------------------------
# korean_ref — spelling the book out for the divider plates (#250)
# ---------------------------------------------------------------------------

def test_korean_ref_spells_the_abbreviation_out() -> None:
    assert korean_ref("삼상 14:23-52") == "사무엘상 14:23-52"
    assert korean_ref("요 1:33-34") == "요한복음 1:33-34"
    assert korean_ref("시 133") == "시편 133"          # chapter-only refs keep their shape


def test_korean_ref_leaves_a_reference_that_is_already_spelled_out() -> None:
    assert korean_ref("요한복음 4:43-54") == "요한복음 4:43-54"


def test_korean_ref_covers_every_book_the_parser_accepts() -> None:
    """Every abbreviation has a full name to grow into — a missing one would silently ship the
    abbreviation onto a divider rather than fail."""
    for abbrev in _KOREAN_BOOKS:
        assert korean_ref(f"{abbrev} 1:1") in {f"{full} 1:1" for full in _KOREAN_FULL_BOOKS}


def test_korean_ref_passes_an_unparseable_reference_through() -> None:
    """A divider subtitle is decoration; an odd reference must not fail the week's build."""
    assert korean_ref("") == ""
    assert korean_ref("눅22:14") == "눅22:14"
    assert korean_ref("Luk 22:14") == "Luk 22:14"
