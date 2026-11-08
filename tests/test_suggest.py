"""Tests for worship_deck.lyrics.suggest — /prep-week spec → review sidecar (#209).

CI-safe: httpx.get is mocked (no respx — see docs/gotchas.md) with a minimal gasazip song page.
The songs are the 2026-11-08 dry run's (data/research, git-ignored), whose misses these pin:
four verses with one identical opener must stay four cards, and "Cx4 - Cx2(목소리)" is six C's.
"""

from __future__ import annotations

import json

import httpx
import pytest

from worship_deck import store
from worship_deck.lyrics import online
from worship_deck.lyrics import suggest as S
from worship_deck.parse import ServiceData

# 주의 자녀로 산다는 것은 — every verse opens with the same line; gasazip prints C after V2 and V4.
_JANYEO = [
    "주의 자녀로 산다는 것은", "불 가운데로 걸어가는 것",
    "그 속에서 신실하게 날 지키시는", "그 손길을 경험하는 것",
    "주의 자녀로 산다는 것은", "바다 위로 걸어가는 것",
    "내 온몸을 덮쳐오는 폭풍 속에서", "잠잠히 주 바라보는 것",
    "때론 불 가운데 휩싸일 때도", "폭풍 가운데 무너질 때도",
    "주님 내 곁에 함께 하시네", "가장 가까이에 함께 하시네",
    "주의 자녀로 산다는 것은", "나도 그들을 용납하는 것",
    "나를 위해 달리신 십자가 사랑", "그 사랑으로 살아가는 것",
    "주의 자녀로 산다는 것은", "주님과 함께 동행하는 것",
    "주께서 지신 십자가 기꺼이 지고", "주와 함께 걸어가는 것",
    "때론 불 가운데 휩싸일 때도", "폭풍 가운데 무너질 때도",
    "주님 내 곁에 함께 하시네", "가장 가까이에 함께 하시네",
]

# 보라 너희는 두려워 말고 — credits line first, then V1 PC C with the chorus printed twice.
_BORA = [
    "보라 너희는 두려워 말고 - 어노인팅",
    "보라 너희는 두려워 말고", "보라 너희를 인도한 나를",
    "너희를 치던 적은 어디 있느냐", "너희를 억누르던 원수는 어디 있느냐",
    "보라 하나님 구원을", "보라 하나님 능력을",
    "너희를 위해서 싸우시는", "주의 손을 보라",
    "보라 하나님 구원을", "보라 하나님 능력을",
    "너희를 위해서 싸우시는", "주의 손을 보라",
]

_PAGES = {"100": _JANYEO, "200": _BORA}


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _gasazip(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Serve _PAGES as gasazip song pages; no throttle, no cache leaking across tests."""
    monkeypatch.setattr(online, "_THROTTLE_S", 0.0)
    online._lyrics_cache.clear()
    calls: list[str] = []

    def get(url: str, **kw: object) -> _FakeResponse:
        calls.append(url)
        body = "<br />\n".join(_PAGES[url.rsplit("/", 1)[1]])
        return _FakeResponse(f'<div id="gasa-desktop" class="x">{body}</div>')

    monkeypatch.setattr(httpx, "get", get)
    return calls


def test_identical_verse_openers_stay_separate_verses() -> None:
    """The dry-run miss: V1+V2 merged and V4 labeled B. Anchors scan forward in spec order, so
    the same opener four times lands on four successive verses; a repeated C is a boundary."""
    lines = S.canonical_lines("100")
    opener = "주의 자녀로 산다는 것은"
    cards, warnings = S.map_sections(lines, [
        {"label": "V1", "at": opener},
        {"label": "V2", "at": opener},
        {"label": "C", "at": "때론 불 가운데 휩싸일"},
        {"label": "V3", "at": opener},
        {"label": "V4", "at": opener},
        {"label": "C", "at": "때론 불 가운데"},
    ])
    assert warnings == []
    assert [c["label"] for c in cards] == ["V1", "V2", "C", "V3", "V4"]
    assert cards[1]["lines"][1] == "바다 위로 걸어가는 것"
    assert cards[4]["lines"] == _JANYEO[16:20]
    assert all(len(c["lines"]) == 4 for c in cards)


def test_sheet_spelling_still_anchors() -> None:
    """Anchors are as read off the sheet: note-split spacing doesn't matter."""
    lines = S.canonical_lines("100")
    assert S.locate(lines, "나 도 그 들 을 용 납 하 는") == (13, 1.0)
    assert S.locate(lines, 13) == (13, 1.0)  # a canonical line number is taken as-is
    assert S.locate(lines, 99) == (-1, 0.0)


def test_credits_before_first_anchor_dropped() -> None:
    lines = S.canonical_lines("200")
    cards, warnings = S.map_sections(lines, [
        {"label": "V1", "at": "보라 너희는 두려워 말고 보라 너희를"},
        {"label": "PC", "at": "너희를 치던 적은"},
        {"label": "C", "at": "보라 하나님 구원을"},
    ])
    assert warnings == ["C: C의 첫 두 줄이 구간 안에 있음 — end로 자르거나 구간을 나누세요"]
    assert cards[0]["lines"] == _BORA[1:3]  # the "제목 - 가수" credit line isn't a lyric
    assert cards[2]["lines"] == _BORA[5:]  # printed twice is kept (warned): `end` cuts a repeat


def test_hymn_page_furniture_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verse numbers and {후렴} markers are page furniture, not slide text."""
    _PAGES["300"] = ["1.죄에서 자유를 얻게함은", "{후렴}", "2 육체의 정욕을", "{후렴}주의 보혈 능력있도다"]
    try:
        assert S.canonical_lines("300") == [
            "죄에서 자유를 얻게함은", "", "육체의 정욕을", "주의 보혈 능력있도다"]
    finally:
        del _PAGES["300"]


def test_end_anchor_cuts_section() -> None:
    lines = S.canonical_lines("200")
    cards, _ = S.map_sections(lines, [{"label": "C", "at": "보라 하나님 구원을", "end": "보라 하나님 능력을"}])
    assert cards == [{"label": "C", "lines": _BORA[5:7]}]


def test_unmatched_anchor_warns() -> None:
    lines = S.canonical_lines("200")
    _, warnings = S.map_sections(lines, [
        {"label": "V1", "at": "보라 너희는 두려워 말고"},
        {"label": "B", "at": "전혀 없는 가사 문장입니다"},
    ])
    assert warnings and warnings[0].startswith("B:")


def test_sheet_repeats_expand_and_unknown_labels_warn() -> None:
    """Dry-run song 3: 'Cx4 - Cx2(목소리)' is the chorus six times; labels match case-insensitively."""
    cards = [{"label": "V1", "lines": ["a"]}, {"label": "C", "lines": ["b"]}]
    assert S.expand_arrangement("Cx4 - Cx2(목소리)", cards) == ("C C C C C C", [])
    arr, warnings = S.expand_arrangement("v1 C×2 TAG", cards)
    assert arr == "V1 C C" and warnings == ["진행 순서에 없는 구간 라벨: TAG"]
    assert S.expand_arrangement("", cards)[1] == ["진행 순서가 비어 있음"]


def test_apply_spec_writes_sidecar_and_leaves_run_alone(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(store, "RUNS_DIR", tmp_path / "runs")
    run = ServiceData(worship_songs=[
        {"title": "주의 자녀로 산다는 것은", "lines": [],
         "provenance": {"source": "gasazip", "song_id": "100", "artist": "GIFTED"}},
        {"title": "", "lines": [], "provenance": {"source": "ocr"}},
    ])
    store.save("2026-11-08", run)
    before = store.path_for("2026-11-08").read_text(encoding="utf-8")
    opener = "주의 자녀로 산다는 것은"
    doc = S.apply_spec("2026-11-08", {"worship_songs": [
        {"ref": 0, "song_id": "100", "sheets": ["003", "004"],
         "sections": [{"label": "V1", "at": opener}, {"label": "V2", "at": opener},
                      {"label": "C", "at": "때론 불 가운데", "end": "가장 가까이에"}],
         "arrangement": "V1 V2 Cx2", "marks": "V1 - V2 - Cx2"},
        {"ref": 1, "continuation_of": 0, "note": "intro strip only"},
    ]})
    assert store.path_for("2026-11-08").read_text(encoding="utf-8") == before
    saved = json.loads(S.sidecar_path("2026-11-08").read_text(encoding="utf-8"))
    assert saved == doc and S.load_sidecar("2026-11-08") == doc
    song, cont = doc["worship_songs"]
    assert song["title"] == "주의 자녀로 산다는 것은" and song["artist"] == "GIFTED"
    assert song["arrangement"] == "V1 V2 C C" and song["warnings"] == []
    assert song["lines"][4] == "" and song["run_title"] == "주의 자녀로 산다는 것은"
    assert cont == {"ref": 1, "run_title": "", "continuation_of": 0, "note": "intro strip only"}


def test_apply_spec_rejects_bad_ref(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(store, "RUNS_DIR", tmp_path / "runs")
    store.save("2026-11-08", ServiceData())
    with pytest.raises(ValueError):
        S.apply_spec("2026-11-08", {"worship_songs": [{"ref": 0, "song_id": "100"}]})


def test_library_song_needs_only_the_play_order(monkeypatch) -> None:
    """A library hit (#204) already has this song's confirmed cards: no song_id, no anchors, no network."""
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: pytest.fail("no network for a library song"))
    run_song = {
        "title": "곡", "provenance": {"source": "library", "slug": "곡"},
        "sections": [{"label": "V1", "lines": ["가"]}, {"label": "C", "lines": ["나"]}],
    }
    rec = S.build_song({"ref": 0, "arrangement": "V1 Cx2 TAG", "marks": "V1 - Cx2"}, run_song)
    assert rec["arrangement"] == "V1 C C" and rec["lines"] == ["가", "", "나"]
    assert [c["label"] for c in rec["sections"]] == ["V1", "C"] and "song_id" not in rec
    assert rec["warnings"] == ["진행 순서에 없는 구간 라벨: TAG"]
    # No arrangement given → a note-only record, nothing for review to apply.
    assert "sections" not in S.build_song({"ref": 0, "note": "?"}, run_song)
    # A non-library song without a song_id stays note-only too.
    assert "sections" not in S.build_song({"ref": 0, "arrangement": "V1"}, {"title": "x", "provenance": {}})
