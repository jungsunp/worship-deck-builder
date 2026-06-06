"""Tests for worship_deck.lyrics.match — attach band-sheet medley to the 찬양 slot."""

from __future__ import annotations

from worship_deck.lyrics.match import _is_choir_row, assign_worship_songs
from worship_deck.lyrics.transcribe import Song


def _worship_order() -> list[dict]:
    """A worship order with both 찬양 rows: opening band slot + 성가대 choir slot."""
    return [
        {"part": "찬 양", "title": "마라나타", "leader": "", "ref": ""},  # band name, not a song
        {"part": "예배의 부름", "title": "", "leader": "강선우 목사", "ref": "눅 11:8-10"},
        {"part": "찬 양", "title": "나의 영원하신 기업", "leader": "성가대", "ref": ""},
        {"part": "봉 헌", "title": "겸손히 주를 섬길 때 (찬 212장)", "leader": "다함께", "ref": ""},
    ]


def test_medley_attaches_to_opening_worship_row_in_order() -> None:
    songs = [Song(title="마라나타", lines=["주 오소서"]), Song(title="주 품에", lines=["주 품에 품으소서"])]
    order = assign_worship_songs(_worship_order(), songs)

    opening = order[0]
    assert opening["part"] == "찬 양" and opening["leader"] == ""
    assert opening["songs"] == songs


def test_choir_row_is_left_untouched() -> None:
    order = assign_worship_songs(_worship_order(), [Song(title="x", lines=["y"])])
    choir = order[2]
    assert choir["leader"] == "성가대"
    assert "songs" not in choir


def test_no_opening_worship_row_is_a_noop() -> None:
    order = [
        {"part": "찬 양", "title": "나의 영원하신 기업", "leader": "성가대", "ref": ""},
        {"part": "봉 헌", "title": "겸손히 주를 섬길 때", "leader": "다함께", "ref": ""},
    ]
    result = assign_worship_songs(order, [Song(title="x", lines=["y"])])
    assert all("songs" not in r for r in result)


def test_empty_songs_attaches_empty_list() -> None:
    order = assign_worship_songs(_worship_order(), [])
    assert order[0]["songs"] == []


def test_is_choir_row_picks_the_non_opening_chanyang_row() -> None:
    order = _worship_order()
    assert _is_choir_row(order[2]) is True  # 찬양 + 성가대 leader
    assert _is_choir_row(order[0]) is False  # opening band 찬양 row
    assert _is_choir_row(order[1]) is False  # 예배의 부름, not 찬양
