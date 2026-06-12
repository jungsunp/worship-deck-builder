"""Tests for worship_deck.lyrics.linebreak — repeat collapse, phrase splits, fallback."""

from __future__ import annotations

import json

import httpx
import pytest

from worship_deck.lyrics import linebreak as L


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


def _split_payload(splits: list[list[str]]) -> dict:
    # Ollama returns the model's structured-output text under "response".
    return {"response": json.dumps({"lines": splits})}


# ---------------------------------------------------------------------------
# collapse_repeats — pure
# ---------------------------------------------------------------------------

def test_collapse_adjacent_phrase_to_x2() -> None:
    line = "온세상 가득하리라 물이 바다덮음같이 물이 바다덮음같이"
    assert L.collapse_repeats(line) == "온세상 가득하리라 물이 바다덮음같이 X 2"


def test_collapse_triple_repeat_to_x3() -> None:
    assert L.collapse_repeats("거룩 거룩 거룩 전능하신 주") == "거룩 X 3 전능하신 주"


def test_collapse_prefers_longest_group() -> None:
    # Two-token group, not two interleaved single-token collapses.
    assert L.collapse_repeats("주께 가오니 주께 가오니") == "주께 가오니 X 2"


def test_collapse_leaves_non_adjacent_repeats() -> None:
    line = "물이 바다덮음같이 여호와의 영광이 물이 바다덮음같이"
    assert L.collapse_repeats(line) == line


def test_collapse_skips_single_syllable_melisma() -> None:
    assert L.collapse_repeats("아 아 아") == "아 아 아"


# ---------------------------------------------------------------------------
# _split_at_space — pure fallback
# ---------------------------------------------------------------------------

def test_split_at_space_fits_all_parts() -> None:
    line = "이전에 있는 것은 모두 잊어버리고 앞에 계신 그리스도께로 달려가 노라"
    parts = L._split_at_space(line, 22)
    assert all(len(p) <= 22 for p in parts)
    assert " ".join(parts) == line  # breaks only at existing spaces


def test_split_at_space_keeps_short_line_whole() -> None:
    assert L._split_at_space("변찮는 주님의 사랑과", 22) == ["변찮는 주님의 사랑과"]


def test_split_at_space_keeps_overlong_word_whole() -> None:
    word = "가" * 30
    assert L._split_at_space(word, 22) == [word]


def test_split_at_space_never_orphans_repeat_suffix() -> None:
    parts = L._split_at_space("온세상 가득하리라 물이 바다덮음같이 X 2", 22)
    assert parts == ["온세상 가득하리라 물이", "바다덮음같이 X 2"]


# ---------------------------------------------------------------------------
# rebreak — collapse + length pass, mocked Ollama
# ---------------------------------------------------------------------------

_LONG = "이전에 있는 것은 모두 잊어버리고 앞에 계신 그리스도께로 달려가 노라"
_GOOD_SPLIT = ["이전에 있는 것은 모두 잊어버리고", "앞에 계신 그리스도께로 달려가 노라"]


def test_rebreak_short_lines_no_http(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*a: object, **kw: object) -> None:
        raise AssertionError("rebreak must not call Ollama when nothing is over-long")

    monkeypatch.setattr(httpx, "post", _boom)
    lines = ["변찮는 주님의 사랑과", "", "거룩한 보혈의 공로를"]
    assert L.rebreak(lines) == lines  # blanks preserved in place


def test_rebreak_uses_valid_model_split(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    def _post(url: str, *, json: dict, timeout: int) -> _FakeResponse:  # noqa: A002
        calls.append(json)
        return _FakeResponse(_split_payload([_GOOD_SPLIT]))

    monkeypatch.setattr(httpx, "post", _post)
    assert L.rebreak(["짧은 줄", _LONG]) == ["짧은 줄", *_GOOD_SPLIT]
    assert len(calls) == 1  # one batched call, over-long lines only
    assert _LONG in calls[0]["prompt"]
    assert "짧은 줄" not in calls[0]["prompt"].split("다음과 같습니다:")[1]


def test_rebreak_falls_back_when_model_alters_text(monkeypatch: pytest.MonkeyPatch) -> None:
    bad = [["이전에 있는 것은 전부 잊어버리고", "앞에 계신 그리스도께로 달려가 노라"]]
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse(_split_payload(bad)))
    parts = L.rebreak([_LONG])
    assert "".join(parts).replace(" ", "") == _LONG.replace(" ", "")
    assert all(len(p) <= L.MAX_CHARS for p in parts)


def test_rebreak_falls_back_when_ollama_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def _post(*a: object, **kw: object) -> None:
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "post", _post)
    parts = L.rebreak([_LONG])  # must not raise
    assert " ".join(parts) == _LONG
    assert all(len(p) <= L.MAX_CHARS for p in parts)


def test_rebreak_uses_ollama_model(monkeypatch: pytest.MonkeyPatch) -> None:
    # One model serves both lyric tasks (2026-06-11 bake-off, docs/gotchas.md).
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:14b")
    seen: dict = {}

    def _post(url: str, *, json: dict, timeout: int) -> _FakeResponse:  # noqa: A002
        seen["model"] = json["model"]
        return _FakeResponse(_split_payload([_GOOD_SPLIT]))

    monkeypatch.setattr(httpx, "post", _post)
    L.rebreak([_LONG])
    assert seen["model"] == "qwen3:14b"


def test_rebreak_collapses_identical_adjacent_lines() -> None:
    assert L.rebreak(["물이 바다덮음같이"] * 3) == ["물이 바다덮음같이 X 3"]


def test_rebreak_does_not_collapse_lines_across_stanza_break() -> None:
    lines = ["물이 바다덮음같이", "", "물이 바다덮음같이"]
    assert L.rebreak(lines) == lines


def test_rebreak_rejects_orphaned_repeat_suffix_from_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    line = "온세상 가득하리라 물이 바다덮음같이 물이 바다덮음같이"
    bad = [["온세상 가득하리라 물이 바다덮음같이 X", "2"]]
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse(_split_payload(bad)))
    assert L.rebreak([line]) == ["온세상 가득하리라 물이", "바다덮음같이 X 2"]
