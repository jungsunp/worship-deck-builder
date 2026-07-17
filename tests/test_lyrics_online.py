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


@pytest.fixture(autouse=True)
def _fresh_online_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero the request throttle and clear the lyric cache — module globals that
    would otherwise slow tests down / leak fetches across them."""
    monkeypatch.setattr(online, "_THROTTLE_S", 0.0)
    online._lyrics_cache.clear()


def _fake_get(
    monkeypatch: pytest.MonkeyPatch, search_fixture: str = "gasazip_search.html"
) -> list[str]:
    """Route online's httpx.get to the fixture pages by URL; returns the list of
    requested URLs (appended live) so tests can assert what was fetched."""
    calls: list[str] = []

    def get(url: str, **kw: object) -> _FakeResponse:
        calls.append(url)
        if "search.html" in url:
            name = search_fixture
        else:
            name = f"gasazip_song_{url.rsplit('/', 1)[1]}.html"
        return _FakeResponse((_FIXTURES / name).read_text(encoding="utf-8"))

    monkeypatch.setattr(httpx, "get", get)
    return calls


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
        "둘째 줄은 이렇게 이어지고",  # trailing "(x2)" repeat mark stripped
        "",  # stanza break — chunk() starts a new slide here
        "새 연은 빈 줄 뒤에 시작한다",  # the mark-only "X 3" line after it is dropped
    ]


def test_fetch_lyrics_without_container_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse("<html></html>"))
    assert online.fetch_lyrics("404") == []


# ---------------------------------------------------------------------------
# _throttled_get — request spacing (gasazip 429s on rapid bursts)
# ---------------------------------------------------------------------------

def test_throttled_get_spaces_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(online, "_THROTTLE_S", 60.0)
    monkeypatch.setattr(online, "_last_request", online.time.monotonic() - 100)
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse("<html></html>"))
    sleeps: list[float] = []
    monkeypatch.setattr(online.time, "sleep", lambda s: sleeps.append(s))

    online._throttled_get(f"{online._BASE}/search.html")  # first request: no wait
    online._throttled_get(f"{online._BASE}/1")
    assert len(sleeps) == 1 and 0 < sleeps[0] <= 60.0


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


# ---------------------------------------------------------------------------
# lookup v2 (#202) — full-row recall, title prefilter, acceptance rule, cache
# ---------------------------------------------------------------------------

def test_title_similar_normalized_containment() -> None:
    assert online._title_similar("하늘의 문을 여소서", "임재 (하늘의 문을 여소서)")
    assert online._title_similar("전능하신 나의 주 하나님", "전능하신 나의주 하나님")  # site spacing
    assert not online._title_similar("하늘의 문을 여소서", "성령의 비가 내리네")
    assert not online._title_similar("주", "주 임재 안에서")  # too short to mean anything


# Sheet-001 shape: OCR fragments fully covering the /507 fixture's lyrics.
_IMJAE_FRAGMENTS = ["하늘의문을 여소서 임 하소서", "주의 영 광 이곳에 가득하 도록"]


def test_lookup_prefilter_reaches_title_similar_row_past_top5(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2026-07-12 sheet 001: the right song sits at row 7 under a parenthesized
    title — the title prefilter fetches it without scoring the six rows above."""
    calls = _fake_get(monkeypatch, "gasazip_search_recall.html")
    match = online.lookup("하늘의 문을 여소서", _IMJAE_FRAGMENTS)
    assert match is not None and match.song_id == "507"
    assert match.cand_cov >= 0.5
    # One search + the single title-similar row; nothing else is fetched.
    assert len(calls) == 2 and calls[1].endswith("/507")


# Sheet-003 shape: the sheet titles the song by its first lyric line.
_FIRSTLINE_FRAGMENTS = [
    "허무한 시절 지날 때에",
    "주가 찾아오 셨네",
    "성령이 오셨네 내 맘에 오셨네",
]


def test_lookup_falls_back_to_site_rank_when_no_title_similar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2026-07-12 sheet 003: no row title resembles the first-line query, but
    gasazip's search indexes lyrics — the right song is in the top rows and
    fragment scoring accepts it (early-exiting before row 3)."""
    calls = _fake_get(monkeypatch, "gasazip_search_firstline.html")
    match = online.lookup("허무한 시절 지날때", _FIRSTLINE_FRAGMENTS)
    assert match is not None and match.song_id == "602"
    assert match.title == "성령이 오셨네"
    assert [c.rsplit("/", 1)[1] for c in calls[1:]] == ["601", "602"]


# Sermonsong shape: OCR fragments = one verse of the /701 fixture's four.
_HYMN_FRAGMENTS = ["예수 사랑 하심은 거룩하신 말일세", "우리들은 약하나 예수권세 많도다"]


def test_lookup_rule_v2_accepts_subset_sheet_on_title_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2026-07-12 sermonsong: the canonical hymn page prints every verse, the sheet
    one — cand_cov can never pass, so a matching title + ocr_cov accepts instead."""
    _fake_get(monkeypatch, "gasazip_search_hymn.html")
    match = online.lookup("예수 사랑하심은", _HYMN_FRAGMENTS)
    assert match is not None and match.song_id == "701"
    assert match.cand_cov < 0.5  # the old rule would have rejected this
    assert match.ocr_cov >= 0.5


def test_lookup_rule_v2_rejects_superset_decoy_without_title_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """High ocr_cov alone must not accept: a long wrong song that happens to contain
    the sheet's text passes only when its title also resembles the query."""
    _fake_get(monkeypatch, "gasazip_search_hymn.html")
    assert online.lookup("완전 무관한 노래제목", _HYMN_FRAGMENTS) is None


def test_fetch_lyrics_cached_across_lookups(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_get(monkeypatch, "gasazip_search_hymn.html")
    online.lookup("예수 사랑하심은", _HYMN_FRAGMENTS)
    online.lookup("완전 무관한 노래제목", _HYMN_FRAGMENTS)
    assert sum(1 for c in calls if c.endswith("/701")) == 1


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
# search_scored (#203) — review re-search: every row scored, no threshold
# ---------------------------------------------------------------------------

def test_search_scored_returns_all_rows_ranked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unlike lookup(), no acceptance threshold — every searched row is returned with
    lyrics populated, best fragment coverage first, for the operator to pick."""
    _fake_get(monkeypatch)
    cands = online.search_scored("보좌 앞으로", _BOJWA_FRAGMENTS)
    assert {c.song_id for c in cands} == {"111", "222", "333"}  # all rows, not just a match
    assert cands[0].song_id == "111"  # fully covered → highest cand_cov, ranked first
    assert cands[0].cand_cov >= cands[-1].cand_cov and cands[0].lines


def test_search_scored_caps_fetches_at_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """`limit` bounds the song-page fetches (latency + gasazip throttle)."""
    calls = _fake_get(monkeypatch)
    online.search_scored("보좌 앞으로", _BOJWA_FRAGMENTS, limit=1)
    assert sum(1 for c in calls if "search.html" not in c) == 1


def test_search_scored_propagates_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """The endpoint catches this to show a message; lookup() swallows it instead."""
    def boom(*a: object, **kw: object) -> None:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "get", boom)
    with pytest.raises(httpx.HTTPError):
        online.search_scored("보좌 앞으로", _BOJWA_FRAGMENTS)


# ---------------------------------------------------------------------------
# Live integration — real gasazip; skipped off-network
# ---------------------------------------------------------------------------

@pytest.mark.local_only
def test_lookup_live_bojwa(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(online, "_THROTTLE_S", 2.5)  # autouse fixture zeroed it
    try:
        httpx.get("http://gasazip.com", timeout=5)
    except httpx.HTTPError:
        pytest.skip("gasazip.com unreachable")
    match = online.lookup("보좌 앞으로", _BOJWA_FRAGMENTS)
    assert match is not None
    assert "보좌" in match.title
    assert any("씻기소서" in ln for ln in match.lines)
