"""Tests for worship_deck.lyrics.transcribe — title detection, online-first, fallback."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from worship_deck.lyrics import transcribe as T
from worship_deck.lyrics.transcribe import Song, transcribe


# ---------------------------------------------------------------------------
# _filter_lyric_fragments — pure, no I/O
# ---------------------------------------------------------------------------

def test_filter_keeps_hangul_drops_chords_numbers_english_urls() -> None:
    raw = [
        "G", "D/F#", "Bm7",                       # chords
        "26", "1.", "= 66",                       # measure numbers / tempo
        "Isaiah 61&One", "https://blog.naver.com/jskyscore",  # english / watermark
        "내 주를 가까이",                          # lyric
        "주님을 가 까 이 함 이",                    # fragmented lyric
    ]
    assert T._filter_lyric_fragments(raw) == ["내 주를 가까이", "주님을 가 까 이 함 이"]


def test_filter_drops_known_hangul_noise() -> None:
    raw = ["도돌이표는 항상 포함입니다", "아이자야씩스티원", "나는 예배하네"]
    assert T._filter_lyric_fragments(raw) == ["나는 예배하네"]


# ---------------------------------------------------------------------------
# _reassemble — mocked Ollama HTTP (no network, no model)
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


def _ollama_payload(songs: list[dict]) -> dict:
    # Ollama returns the model's structured-output text under "response".
    return {"response": json.dumps({"songs": songs})}


def test_reassemble_parses_songs(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    payload = _ollama_payload(
        [{"title": "부르신 곳에서", "lines": ["나는 예배하네", "어떤 상황에도 나는 예배하네"]}]
    )
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse(payload))

    songs = T._reassemble(["나는예배하네 -", "어떤상황에도 -"])
    assert songs == [
        Song(title="부르신 곳에서", lines=["나는 예배하네", "어떤 상황에도 나는 예배하네"])
    ]


def test_reassemble_drops_blank_lines_and_empty_songs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Blank lyric lines are stripped and an empty trailing song is dropped."""
    import httpx

    payload = _ollama_payload(
        [
            {"title": "실제곡", "lines": ["가사 한 줄", "  ", "", "가사 두 줄"]},
            {"title": "", "lines": []},  # empty trailing song dropped
        ]
    )
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse(payload))

    assert T._reassemble(["x"]) == [Song(title="실제곡", lines=["가사 한 줄", "가사 두 줄"])]


def test_reassemble_sends_model_and_format(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    captured: dict = {}

    def fake_post(url: str, **kw: object) -> _FakeResponse:
        captured["url"] = url
        captured["json"] = kw.get("json", {})
        return _FakeResponse(_ollama_payload([]))

    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:14b")
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    monkeypatch.setattr(httpx, "post", fake_post)

    T._reassemble(["가사"])

    assert captured["url"] == "http://127.0.0.1:11434/api/generate"
    body = captured["json"]
    assert body["model"] == "qwen3:14b"
    assert body["stream"] is False
    assert body["think"] is True                        # better recall/spacing on qwen3:14b
    assert body["format"]["required"] == ["songs"]      # structured JSON output
    assert body["options"]["temperature"] == 0


def test_reassemble_reads_thinking_field_when_response_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Thinking models (qwen3.5) put structured output in `thinking`, not `response`."""
    import httpx

    payload = {
        "response": "",
        "thinking": json.dumps({"songs": [{"title": "T", "lines": ["가사"]}]}),
    }
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse(payload))

    songs = T._reassemble(["가사"])
    assert songs == [Song(title="T", lines=["가사"])]


def test_reassemble_raises_when_ollama_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    def boom(*a: object, **kw: object) -> None:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(RuntimeError, match="Ollama request"):
        T._reassemble(["가사"])


# ---------------------------------------------------------------------------
# _detect_title — tallest Hangul line near the top, edge tokens trimmed
# ---------------------------------------------------------------------------

def test_detect_title_real_sheet_shape() -> None:
    # Shape of the real 보좌 앞으로 sheet: a taller handwritten mark with no Hangul,
    # the title with a merged red "•all" mark, then watermark/credits and lyrics.
    lines = [
        (0.0634, 'vx3(aim) - VX3 (ky change "F")'),
        (0.0474, "•all 보좌 앞으로"),
        (0.0269, "blog.naver.com/x 주님의 보혈 의지하는 Words & Music by 민호기"),
        (0.0318, "E B/D# C#m G#m/B"),
        (0.0444, "V 주님의 보혈 . 의지하 는맘 .으로"),
    ]
    assert T._detect_title(lines) == "보좌 앞으로"


def test_detect_title_skips_noise_and_handles_empty() -> None:
    assert T._detect_title([]) == ""
    assert T._detect_title([(0.05, "VX3 chords only")]) == ""
    # Known Hangul noise (watermark phonetics) never becomes the title.
    assert T._detect_title([(0.09, "아이자야씩스티원"), (0.04, "나는 예배하네")]) == "나는 예배하네"


def test_detect_title_ignores_taller_handwritten_marks() -> None:
    # Real sheet-2 shape: handwriting with some Hangul ("드럼만") out-talls the
    # printed title but is mostly latin/digits — the ratio filter rejects it.
    lines = [
        (0.0380, "181-8182--82-Cnter.-v3-74-6x4 all"),
        (0.0526, "드럼만 - ((83)"),
        (0.0300, "죄에서 자유를 얻게 함은"),
        (0.0237, "Hymn 268 • 천천히 L.E.Jones, 1889"),
    ]
    assert T._detect_title(lines) == "죄에서 자유를 얻게 함은"


def test_detect_title_rejects_lyric_lines_on_continuation_pages() -> None:
    # Continuation pages have no printed title; their tallest Hangul is a note-split
    # lyric line, which the Hangul length cap rejects → "" → no online lookup.
    lines = [
        (0.0919, 'CX3-B-CXX-C (주의 보혈")'),
        (0.0486, "포- 대를 향하여- 그리- 스도 예수안-에서- 부름 의상을-위하-여 달려가 - 노라-"),
    ]
    assert T._detect_title(lines) == ""


# ---------------------------------------------------------------------------
# transcribe — orchestration with all stages mocked
# ---------------------------------------------------------------------------

_OCR_LINES = [
    (0.05, "내 주를 가까이"),  # tallest Hangul line → title
    (0.02, "G"),
    (0.03, "내 주 를"),
    (0.03, "가까이"),
    (0.02, "https://x"),
]


def test_transcribe_uses_online_match_when_confident(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from worship_deck.lyrics import online

    monkeypatch.setattr(T, "_vision_ocr", lambda p: _OCR_LINES)
    seen: dict = {}

    def fake_lookup(title: str, fragments: list[str]) -> online.Candidate:
        seen["title"], seen["fragments"] = title, fragments
        return online.Candidate(
            song_id="1", title="내 주를 가까이", artist="x", lines=["내 주를 가까이 하게 함은"]
        )

    monkeypatch.setattr(online, "lookup", fake_lookup)
    songs = transcribe("whatever.png")

    assert songs == [Song(title="내 주를 가까이", lines=["내 주를 가까이 하게 함은"])]
    assert seen["title"] == "내 주를 가까이"
    # Lookup ranks against the filtered Hangul fragments only.
    assert "https://x" not in seen["fragments"] and "G" not in seen["fragments"]


def test_transcribe_rebreaks_overlong_online_lines_without_ollama(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An over-long gasazip line is re-broken (#126) even with no Ollama running."""
    import httpx

    from worship_deck.lyrics import online

    monkeypatch.setattr(T, "_vision_ocr", lambda p: _OCR_LINES)
    long_line = "이전에 있는 것은 모두 잊어버리고 앞에 계신 그리스도께로 달려가 노라"
    monkeypatch.setattr(
        online,
        "lookup",
        lambda *a, **kw: online.Candidate(
            song_id="1", title="내 주를 가까이", artist="x", lines=[long_line]
        ),
    )

    def fake_post(*a: object, **kw: object) -> None:
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "post", fake_post)
    (song,) = transcribe("whatever.png")

    assert len(song.lines) > 1  # split, not passed through
    assert " ".join(song.lines) == long_line  # rule-based fallback, text preserved


def test_transcribe_falls_back_to_reassembly_with_detected_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    from worship_deck.lyrics import online

    monkeypatch.setattr(T, "_vision_ocr", lambda p: _OCR_LINES)
    monkeypatch.setattr(online, "lookup", lambda *a, **kw: None)  # no online match
    seen: dict = {}

    def fake_post(url: str, **kw: object) -> _FakeResponse:
        seen["prompt"] = kw["json"]["prompt"]
        return _FakeResponse(
            _ollama_payload([{"title": "내 주를 가까이", "lines": ["내 주를 가까이"]}])
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    songs = transcribe("whatever.png")

    assert songs == [Song(title="내 주를 가까이", lines=["내 주를 가까이"])]
    # Only the Hangul fragments reach the model — chords/URLs filtered out.
    assert "내 주 를" in seen["prompt"] and "가까이" in seen["prompt"]
    assert "https://x" not in seen["prompt"] and "\nG\n" not in seen["prompt"]
    # The deterministically detected title is handed to the model, not guessed.
    assert '곡 제목은 "내 주를 가까이"' in seen["prompt"]


# ---------------------------------------------------------------------------
# chunk — pure grouping into <= max_lines slides
# ---------------------------------------------------------------------------

def test_chunk_empty_and_all_blank() -> None:
    assert T.chunk([]) == []
    assert T.chunk(["", "   ", "\t"]) == []


def test_chunk_single_line() -> None:
    assert T.chunk(["나는 예배하네"]) == [["나는 예배하네"]]


def test_chunk_exactly_max_lines_is_one_slide() -> None:
    assert T.chunk(["a", "b"]) == [["a", "b"]]


def test_chunk_groups_by_count_default_two() -> None:
    assert T.chunk(["a", "b", "c"]) == [["a", "b"], ["c"]]


def test_chunk_blank_line_forces_break() -> None:
    assert T.chunk(["a", "", "b"]) == [["a"], ["b"]]


def test_chunk_stanza_longer_than_max_splits_within_stanza() -> None:
    # A 3-line stanza still splits by count; the blank only ends the prior stanza.
    assert T.chunk(["a", "b", "c", "", "d"]) == [["a", "b"], ["c"], ["d"]]


def test_chunk_collapses_leading_trailing_and_repeated_blanks() -> None:
    assert T.chunk(["", "", "a", "b", "", "", "c", "", ""]) == [["a", "b"], ["c"]]


def test_chunk_whitespace_only_line_is_a_break() -> None:
    assert T.chunk(["a", "   ", "b"]) == [["a"], ["b"]]


def test_chunk_custom_max_lines() -> None:
    assert T.chunk(["a", "b", "c", "d"], max_lines=3) == [["a", "b", "c"], ["d"]]


# ---------------------------------------------------------------------------
# Live integration — real Vision + Ollama; skipped without the toolchain/sheets
# ---------------------------------------------------------------------------

_DATA = Path(__file__).parent.parent / "data"


@pytest.mark.local_only
def test_transcribe_live_hybrid() -> None:
    """Vision + Qwen on real sheets, incl. sheet-3 which crashed the vision-mode runner."""
    import httpx

    if shutil.which("swift") is None:
        pytest.skip("swift (Xcode CLT) not available")
    sheet = _DATA / "sheet-3.jpeg"
    if not sheet.exists():
        pytest.skip("real band sheet not present in data/")
    host = "http://127.0.0.1:11434"
    try:
        httpx.get(f"{host}/api/version", timeout=2)
    except httpx.HTTPError:
        pytest.skip("ollama server not running")

    songs = transcribe(str(sheet))
    all_lyrics = " ".join(line for s in songs for line in s.lines)
    assert "예배하네" in all_lyrics
