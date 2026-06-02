"""Tests for worship_deck.lyrics.choir — pure parser, no Mac/API/network."""

from __future__ import annotations

from worship_deck.lyrics.choir import parse_choir_text
from worship_deck.lyrics.transcribe import Song

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


def test_empty_input_returns_empty_song() -> None:
    assert parse_choir_text("   \n\n  ") == Song(title="")
