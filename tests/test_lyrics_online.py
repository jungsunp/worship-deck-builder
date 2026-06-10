"""Tests for worship_deck.lyrics.online — gasazip canonical-lyrics lookup (#110).

httpx.get is mocked directly (no respx — see docs/gotchas.md) with trimmed replicas of
real gasazip markup in tests/fixtures/gasazip_*.html.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from worship_deck.lyrics import online

_FIXTURES = Path(__file__).parent / "fixtures"

# OCR-ish fragments from the 보좌 앞으로 sheet: note-split syllables, repeated for the
# second key, plus a chord-line leftover. The /111 fixture's lyrics are fully covered.
_BOJWA_FRAGMENTS = [
    "주님의 보혈 . 의지하 는맘 .으로",
    "보좌앞 에 지금가 오니 . 날 씻기 소서",
    "사모하는영 혼을 . 받 아주 소서",
    "주 님 의 보혈 의지하 는맘 으로",
    "보좌앞에 지금가오니 날 씻기소서",
    "사모하는영 혼을 받아주소서",
]


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        pass


def _fake_get(monkeypatch: pytest.MonkeyPatch) -> None:
    """Route online's httpx.get to the fixture pages by URL."""

    def get(url: str, **kw: object) -> _FakeResponse:
        if "search.html" in url:
            name = "gasazip_search.html"
        else:
            name = f"gasazip_song_{url.rsplit('/', 1)[1]}.html"
        return _FakeResponse((_FIXTURES / name).read_text(encoding="utf-8"))

    monkeypatch.setattr(httpx, "get", get)


# ---------------------------------------------------------------------------
# search — result-row parsing
# ---------------------------------------------------------------------------

def test_search_parses_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_get(monkeypatch)
    results = online.search("보좌 앞으로")
    assert [(c.song_id, c.title, c.artist) for c in results] == [
        ("222", "보좌 앞으로", "다른워십"),
        ("111", "보좌 앞으로", "찬미워십"),
        ("333", "은혜의 보좌", "파이디온선교회"),
    ]


def test_search_ignores_related_row_markup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Song pages list related songs with class-before-href anchors — not results."""
    _fake_get(monkeypatch)
    assert "999" not in [c.song_id for c in online.search("보좌 앞으로")]


# ---------------------------------------------------------------------------
# fetch_lyrics — <br/> folding and stanza breaks
# ---------------------------------------------------------------------------

def test_fetch_lyrics_folds_br_plus_newline(monkeypatch: pytest.MonkeyPatch) -> None:
    """`<br />\\n` in the markup is one line break, not a stanza break."""
    _fake_get(monkeypatch)
    assert online.fetch_lyrics("111") == [
        "주님의보혈 의지하는맘으로 보좌앞에 지금가오니",
        "날 씻기소서 사모하는영혼을 받아주소서",
    ]


def test_fetch_lyrics_keeps_double_br_as_stanza_break(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_get(monkeypatch)
    assert online.fetch_lyrics("222") == [
        "전혀 다른 노래의 가사 첫 줄",
        "둘째 줄은 이렇게 이어지고",
        "",  # stanza break — chunk() starts a new slide here
        "새 연은 빈 줄 뒤에 시작한다",
    ]


def test_fetch_lyrics_without_container_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse("<html></html>"))
    assert online.fetch_lyrics("404") == []


# ---------------------------------------------------------------------------
# lookup — fragment ranking, threshold, error fallback
# ---------------------------------------------------------------------------

def test_lookup_picks_fragment_match_over_site_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same-title decoy is listed first; the OCR fragments select the right song."""
    _fake_get(monkeypatch)
    match = online.lookup("보좌 앞으로", _BOJWA_FRAGMENTS)
    assert match is not None
    assert match.song_id == "111"
    assert match.title == "보좌 앞으로"
    assert match.lines[0].startswith("주님의보혈")


def test_lookup_below_threshold_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_get(monkeypatch)
    assert online.lookup("보좌 앞으로", ["완전히 무관한 어떤 글자들"]) is None


def test_lookup_network_error_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: object, **kw: object) -> None:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "get", boom)
    assert online.lookup("보좌 앞으로", _BOJWA_FRAGMENTS) is None


def test_lookup_no_results_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse("<html></html>"))
    assert online.lookup("듣도보도 못한 곡", _BOJWA_FRAGMENTS) is None


def test_strip_header_drops_title_artist_line_only() -> None:
    cand = online.Candidate(
        song_id="1",
        title="죄에서 자유를 얻게함은",
        artist="인순이",
        lines=["죄에서 자유를 얻게 함은 - 인순이", "죄에서 자유를 얻게 함은 보혈의 능력"],
    )
    online._strip_header(cand)
    assert cand.lines == ["죄에서 자유를 얻게 함은 보혈의 능력"]

    # A first line that's a real lyric (no artist in it) is left alone.
    cand2 = online.Candidate(
        song_id="2", title="보좌 앞으로", artist="찬미워십", lines=["주님의보혈 의지하는맘으로"]
    )
    online._strip_header(cand2)
    assert cand2.lines == ["주님의보혈 의지하는맘으로"]


# ---------------------------------------------------------------------------
# Live integration — real gasazip; skipped off-network
# ---------------------------------------------------------------------------

@pytest.mark.local_only
def test_lookup_live_bojwa() -> None:
    try:
        httpx.get("http://gasazip.com", timeout=5)
    except httpx.HTTPError:
        pytest.skip("gasazip.com unreachable")
    match = online.lookup("보좌 앞으로", _BOJWA_FRAGMENTS)
    assert match is not None
    assert "보좌" in match.title
    assert any("씻기소서" in ln for ln in match.lines)
