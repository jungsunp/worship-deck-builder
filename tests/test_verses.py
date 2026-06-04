"""Tests for worship_deck.bible.verses.lookup().

fetch_esv is mocked so the test runs without ESV_API_KEY.
"""

from __future__ import annotations

import pytest

import worship_deck.bible.verses as verses_mod
from worship_deck.bible.verses import (
    Passage,
    Verse,
    _split_esv_verses,
    lookup,
    lookup_verses,
    verse_labels,
)


def test_lookup_returns_passage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verses_mod, "fetch_esv", lambda ref: "For God so loved the world")
    result = lookup("요 3:16")
    assert isinstance(result, Passage)
    assert result.reference == "요 3:16"
    assert "하나님" in result.korean
    assert result.english == "For God so loved the world"


# ---------------------------------------------------------------------------
# verse assembly: _split_esv_verses / lookup_verses / verse_labels
# ---------------------------------------------------------------------------


def test_split_esv_verses_parses_bracketed_numbers() -> None:
    assert _split_esv_verses("[14] foo [15] bar baz") == {14: "foo", 15: "bar baz"}


def test_split_esv_verses_condenses_poetry_line_breaks() -> None:
    # ESV returns poetry (e.g. Psalms) with internal newlines + indentation; condense them.
    raw = "[1] Behold, how good\n    when brothers dwell in unity! [2] It is like\n  the oil"
    assert _split_esv_verses(raw) == {
        1: "Behold, how good when brothers dwell in unity!",
        2: "It is like the oil",
    }


def test_lookup_verses_condenses_both_languages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verses_mod, "fetch_esv", lambda ref: "[1] a\n   b [2] c\nd [3] e")
    result = lookup_verses("시 133:1-3")
    assert all("\n" not in v.english and "  " not in v.english for v in result)
    assert all("\n" not in v.korean for v in result)


def test_lookup_verses_aligns_kr_and_esv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        verses_mod,
        "fetch_esv",
        lambda ref: "[1] one [2] two [3] three",
    )
    result = lookup_verses("시 133:1-3")
    assert [v.number for v in result] == [1, 2, 3]
    assert all(isinstance(v, Verse) for v in result)
    assert all(v.korean for v in result)  # real KRV text present
    assert [v.english for v in result] == ["one", "two", "three"]


def test_verse_labels_builds_both_languages() -> None:
    kr, en = verse_labels("시 133:1-3")
    assert kr == "[시 133:1-3, 개역한글]"
    assert en == "[Psalms 133:1-3, ESV]"
