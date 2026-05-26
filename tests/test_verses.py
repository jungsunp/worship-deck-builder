"""Tests for worship_deck.bible.verses.lookup().

fetch_esv is mocked so the test runs without ESV_API_KEY.
"""

from __future__ import annotations

import pytest

import worship_deck.bible.verses as verses_mod
from worship_deck.bible.verses import Passage, lookup


def test_lookup_returns_passage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verses_mod, "fetch_esv", lambda ref: "For God so loved the world")
    result = lookup("요 3:16")
    assert isinstance(result, Passage)
    assert result.reference == "요 3:16"
    assert "하나님" in result.korean
    assert result.english == "For God so loved the world"
