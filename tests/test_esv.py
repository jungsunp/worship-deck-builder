"""Tests for worship_deck.bible.esv — ESV API client."""

from __future__ import annotations

import pytest

from worship_deck.bible.ref import BibleRef, parse_ref
from worship_deck.bible.esv import _ref_to_query, fetch_esv


# ---------------------------------------------------------------------------
# _ref_to_query — pure function, no mocking needed
# ---------------------------------------------------------------------------

def test_query_chapter_only() -> None:
    assert _ref_to_query(BibleRef("Psalms", 133, None, None)) == "Psalms 133"


def test_query_single_verse() -> None:
    assert _ref_to_query(BibleRef("Luke", 22, 14, None)) == "Luke 22:14"


def test_query_verse_range() -> None:
    assert _ref_to_query(BibleRef("Luke", 22, 14, 24)) == "Luke 22:14-24"


def test_query_numbered_book() -> None:
    assert _ref_to_query(BibleRef("1 Corinthians", 13, 1, 13)) == "1 Corinthians 13:1-13"


# ---------------------------------------------------------------------------
# fetch_esv — mocked HTTP
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, data: dict) -> None:
        self._data = data

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._data


def test_fetch_esv_returns_stripped_text(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    monkeypatch.setenv("ESV_API_KEY", "test-key")
    monkeypatch.setattr(
        httpx, "get", lambda *a, **kw: _FakeResponse({"passages": ["  verse text\n"]})
    )

    result = fetch_esv(BibleRef("Luke", 22, 14, 24))
    assert result == "verse text"


def test_fetch_esv_sends_correct_params(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    captured: dict = {}

    def mock_get(url: str, **kw: object) -> _FakeResponse:
        captured["url"] = url
        captured["params"] = kw.get("params", {})
        captured["headers"] = kw.get("headers", {})
        return _FakeResponse({"passages": ["text"]})

    monkeypatch.setenv("ESV_API_KEY", "test-key")
    monkeypatch.setattr(httpx, "get", mock_get)

    fetch_esv(BibleRef("Luke", 22, 14, 24))

    assert captured["url"] == "https://api.esv.org/v3/passage/text/"
    assert captured["params"]["q"] == "Luke 22:14-24"
    assert captured["params"]["include-headings"] == "false"
    assert captured["params"]["include-footnotes"] == "false"
    assert captured["params"]["include-verse-numbers"] == "true"
    assert captured["params"]["include-short-copyright"] == "false"
    assert captured["params"]["include-passage-references"] == "false"


def test_fetch_esv_sends_auth_header(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    captured: dict = {}

    def mock_get(url: str, **kw: object) -> _FakeResponse:
        captured["headers"] = kw.get("headers", {})
        return _FakeResponse({"passages": ["text"]})

    monkeypatch.setenv("ESV_API_KEY", "my-secret-key")
    monkeypatch.setattr(httpx, "get", mock_get)

    fetch_esv(BibleRef("Psalms", 133, None, None))

    assert captured["headers"]["Authorization"] == "Token my-secret-key"


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ESV_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ESV_API_KEY"):
        fetch_esv(BibleRef("Luke", 22, 14, 24))


def test_http_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    class _ErrorResponse:
        def raise_for_status(self) -> None:
            raise httpx.HTTPStatusError("403", request=None, response=None)  # type: ignore[arg-type]

        def json(self) -> dict:
            return {}

    monkeypatch.setenv("ESV_API_KEY", "test-key")
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _ErrorResponse())

    with pytest.raises(httpx.HTTPStatusError):
        fetch_esv(BibleRef("Luke", 22, 14, 24))


# ---------------------------------------------------------------------------
# Live integration test — skipped in CI
# ---------------------------------------------------------------------------

@pytest.mark.local_only
def test_fetch_esv_live() -> None:
    import os

    if not os.environ.get("ESV_API_KEY"):
        pytest.skip("ESV_API_KEY not set")
    ref = parse_ref("눅 22:14-24")
    text = fetch_esv(ref)
    assert "[14]" in text
    assert "passover" in text.lower()
