"""Tests for worship_deck.library — persistent confession-song store."""

from __future__ import annotations

import pytest

from worship_deck import library


@pytest.fixture(autouse=True)
def _library_dir(tmp_path, monkeypatch):
    """Redirect the library to a tmp dir (mirrors test_store patching RUNS_DIR)."""
    monkeypatch.setattr(library, "LIBRARY_DIR", tmp_path / "library")


def _song() -> dict:
    return {
        "title": "주 은혜임을",
        "lines": ["주 은혜임을", "", "내 모든 삶"],
        "composer": "작곡가",
        "sections": [
            {"label": "V1", "lines": ["주 은혜임을"]},
            {"label": "C", "lines": ["내 모든 삶"]},
        ],
        "arrangement": "V1 C V1 Cx2",
    }


def test_round_trip() -> None:
    slug = library.save_song(_song())
    assert library.load_song(slug) == _song()


def test_legacy_song_gets_default_structure() -> None:
    """A song saved without section info stores empty sections/arrangement (persist-forward)."""
    slug = library.save_song({"title": "옛곡", "lines": ["가사"], "composer": "작곡가"})
    loaded = library.load_song(slug)
    assert loaded["sections"] == []
    assert loaded["arrangement"] == ""


def test_slug_keeps_hangul_and_lowercases() -> None:
    assert library._slug("주 은혜임을 Amazing!") == "주-은혜임을-amazing"


def test_slug_falls_back_to_hash_when_empty() -> None:
    assert library._slug("!!!").startswith("song-")


def test_save_overwrites_same_song() -> None:
    library.save_song(_song())
    library.save_song({**_song(), "composer": "다른 작곡가"})
    songs = library.list_songs()
    assert len(songs) == 1
    assert songs[0]["composer"] == "다른 작곡가"


def test_list_sorted_by_title() -> None:
    library.save_song({"title": "나중에", "lines": []})
    library.save_song({"title": "가나다", "lines": []})
    assert [s["title"] for s in library.list_songs()] == ["가나다", "나중에"]


def test_list_empty_when_no_library() -> None:
    assert library.list_songs() == []


def test_load_missing_returns_none() -> None:
    assert library.load_song("nope") is None


def test_save_requires_title() -> None:
    with pytest.raises(ValueError):
        library.save_song({"title": "  ", "lines": ["a"]})


def test_load_rejects_traversal() -> None:
    with pytest.raises(ValueError):
        library.load_song("../secret")
