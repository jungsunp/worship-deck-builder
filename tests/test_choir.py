"""Tests for worship_deck.lyrics.choir — pure parser, no Mac/API/network."""

from __future__ import annotations

from worship_deck.lyrics.choir import parse_choir_text
from worship_deck.lyrics.transcribe import Song, chunk

# Two sample choir blocks: title line + composer/arranger line + line-broken lyrics.
_SONG_A = """\
주 하나님 지으신 모든 세계
스튜어트 하인 작곡

주 하나님 지으신 모든 세계
내 마음 속에 그리어 볼 때
하늘의 별 울려 퍼지는 뇌성
주님의 권능 우주에 찼네
"""

_SONG_B = """\
거룩한 성전에
박재훈 편곡

거룩한 성전에 주님 계시니
온 땅은 잠잠하라 그 앞에서
"""


def test_parses_title_composer_and_ordered_lyrics() -> None:
    assert parse_choir_text(_SONG_A) == Song(
        title="주 하나님 지으신 모든 세계",
        composer="스튜어트 하인 작곡",
        lines=[
            "주 하나님 지으신 모든 세계",
            "내 마음 속에 그리어 볼 때",
            "하늘의 별 울려 퍼지는 뇌성",
            "주님의 권능 우주에 찼네",
        ],
    )


def test_parses_second_sample_block() -> None:
    assert parse_choir_text(_SONG_B) == Song(
        title="거룩한 성전에",
        composer="박재훈 편곡",
        lines=["거룩한 성전에 주님 계시니", "온 땅은 잠잠하라 그 앞에서"],
    )


def test_composer_detected_by_marker_not_position() -> None:
    """A composer line further down (extra blank/credit lines above) is still found."""
    raw = "제목\n작사자 미상\n홍길동 작곡\n가사 한 줄\n"
    song = parse_choir_text(raw)
    assert song.title == "제목"
    assert song.composer == "홍길동 작곡"
    assert song.lines == ["작사자 미상", "가사 한 줄"]


def test_no_composer_line_leaves_composer_empty() -> None:
    song = parse_choir_text("제목\n가사 한 줄\n가사 두 줄\n")
    assert song.composer == ""
    assert song.lines == ["가사 한 줄", "가사 두 줄"]


def test_composer_without_marker_taken_when_isolated() -> None:
    """An English credit (no 작곡/편곡) right after the title, set off by a blank, is the composer."""
    raw = "오 찬양해 우리 주께\nStan Pethel\n\n오 찬양해 우리 주께\n그 이름 송축하라\n"
    song = parse_choir_text(raw)
    assert song.title == "오 찬양해 우리 주께"
    assert song.composer == "Stan Pethel"
    assert song.lines == ["오 찬양해 우리 주께", "그 이름 송축하라"]


def test_empty_input_returns_empty_song() -> None:
    assert parse_choir_text("   \n\n  ") == Song(title="")


def test_interior_blank_lines_preserved_as_stanza_breaks() -> None:
    """Blank lines between stanzas survive so chunk() starts each stanza on a new slide."""
    raw = "제목\n작곡자 작곡\n\n높은 산이\n거친 들이\n\n그 어디나\n할렐루야\n"
    song = parse_choir_text(raw)
    assert song.lines == ["높은 산이", "거친 들이", "", "그 어디나", "할렐루야"]
    assert chunk(song.lines) == [
        ["높은 산이", "거친 들이"],
        ["그 어디나", "할렐루야"],
    ]


def test_zero_width_lines_are_stanza_breaks() -> None:
    """The pasted source separates stanzas with U+200B-only lines (2026-08-09 \uc131\uac00\ub300):
    invisible, but `strip()` leaves them non-blank, so each one used to ride onto the next
    slide as a lyric line and shift the whole rest of the section."""
    raw = "\uc81c\ubaa9\n\uc791\uace1\uc790 \uc791\uace1\n\n\ub192\uc740 \uc0b0\uc774\n\uac70\uce5c \ub4e4\uc774\n\u200b\n\uadf8 \uc5b4\ub514\ub098\n\ud560\ub810\ub8e8\uc57c\n"
    song = parse_choir_text(raw)
    assert song.lines == ["\ub192\uc740 \uc0b0\uc774", "\uac70\uce5c \ub4e4\uc774", "", "\uadf8 \uc5b4\ub514\ub098", "\ud560\ub810\ub8e8\uc57c"]
    assert chunk(song.lines) == [
        ["\ub192\uc740 \uc0b0\uc774", "\uac70\uce5c \ub4e4\uc774"],
        ["\uadf8 \uc5b4\ub514\ub098", "\ud560\ub810\ub8e8\uc57c"],
    ]


def test_interlude_marker_dropped() -> None:
    """A 간주 line (with or without parens) is dropped, not paired into a lyric slide."""
    raw = "제목\n작곡자 작곡\n\n높은 산이\n간주\n(간주)\n그 어디나\n"
    song = parse_choir_text(raw)
    assert song.lines == ["높은 산이", "그 어디나"]
