"""Tests for worship_deck.lyrics.linebreak — greedy space splits to fit the lyric banner."""

from __future__ import annotations

from worship_deck.lyrics import linebreak as L

# ---------------------------------------------------------------------------
# _split_at_space
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


# ---------------------------------------------------------------------------
# rebreak
# ---------------------------------------------------------------------------

_LONG = "이전에 있는 것은 모두 잊어버리고 앞에 계신 그리스도께로 달려가 노라"


def test_rebreak_leaves_short_lines_and_blanks_alone() -> None:
    lines = ["변찮는 주님의 사랑과", "", "거룩한 보혈의 공로를"]
    assert L.rebreak(lines) == lines  # blanks preserved in place (stanza breaks)


def test_rebreak_splits_overlong_line_preserving_text() -> None:
    parts = L.rebreak(["짧은 줄", _LONG])
    assert parts[0] == "짧은 줄"
    assert " ".join(parts[1:]) == _LONG
    assert all(len(p) <= L.MAX_CHARS for p in parts)


def test_rebreak_keeps_repeated_lines_verbatim() -> None:
    # Repeats are never collapsed to "… X N" — the operator reads slides against the
    # sheet while labeling sections, and the literal repeat reads better (2026-07-16).
    assert L.rebreak(["물이 바다덮음같이"] * 3) == ["물이 바다덮음같이"] * 3


def test_rebreak_is_io_free() -> None:
    # The Ollama phrase-splitter is gone (#213) — nothing here may touch the network.
    import inspect

    assert "httpx" not in inspect.getsource(L)
