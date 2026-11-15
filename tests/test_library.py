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


# ── worship library (#204) ────────────────────────────────────────────────────

_MEDLEY = {
    "title": "주의 자녀로 산다는 것은",
    "composer": "",
    "lines": ["주의 자녀로 산다는 것은", "불 가운데로 걸어가는 것", "", "때론 불 가운데 휩싸일 때도", "폭풍 가운데 무너질 때도"],
    "sections": [
        {"label": "V1", "lines": ["주의 자녀로 산다는 것은", "불 가운데로 걸어가는 것"]},
        {"label": "C", "lines": ["때론 불 가운데 휩싸일 때도", "폭풍 가운데 무너질 때도"]},
    ],
    "arrangement": "V1 C C",
}


def test_worship_library_is_separate_from_confession(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(library, "WORSHIP_DIR", tmp_path / "worship")
    slug = library.save_song(_MEDLEY, library.WORSHIP_DIR)
    assert library.load_song(slug, library.WORSHIP_DIR) == _MEDLEY
    assert library.load_song(slug) is None  # not in the confession library
    assert [s["title"] for s in library.list_songs(library.WORSHIP_DIR)] == [_MEDLEY["title"]]
    assert library.list_songs() == []


def test_match_worship_by_ocr_fragments(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(library, "WORSHIP_DIR", tmp_path / "worship")
    library.save_song(_MEDLEY, library.WORSHIP_DIR)
    # Note-split syllables, as Vision reads them off the staff; the title is a misread.
    fragments = ["주의 자녀로 산 다 는 것 은", "불 가운데로 걸어 가 는 것", "때론 불 가운데 휩싸 일 때도", "폭풍 가운데 무너 질 때도"]
    song, cand_cov, ocr_cov = library.match_worship(["엉뚱한 제목"], fragments)
    assert song["title"] == _MEDLEY["title"] and song["slug"] == "주의-자녀로-산다는-것은"
    assert cand_cov >= 0.5 and ocr_cov >= 0.5


def test_match_worship_by_title_needs_some_lyric_overlap(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(library, "WORSHIP_DIR", tmp_path / "worship")
    library.save_song(_MEDLEY, library.WORSHIP_DIR)
    # Same title, different song's lyrics: the title alone must not pull in the saved text.
    other = ["주의 자녀로 산다는 것은", "전혀 다른 노래의 가사입니다", "완전히 새로운 곡이에요", "나는 예배하네 주님께"]
    assert library.match_worship(["주의 자녀로 산다는 것은"], other) is None
    assert library.match_worship(["주의 자녀로 산다는 것은"], []) is None  # nothing read off the sheet


def test_match_worship_empty_or_missing_library(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(library, "WORSHIP_DIR", tmp_path / "does-not-exist")
    assert library.match_worship(["제목"], ["가사 한 줄"]) is None


def test_backfill_takes_newest_text_and_dry_run_writes_nothing(tmp_path, monkeypatch) -> None:
    import json

    monkeypatch.setattr(library, "WORSHIP_DIR", tmp_path / "worship")
    runs = tmp_path / "runs"
    runs.mkdir()
    gz, lib = {"source": "gasazip"}, {"source": "library"}
    old = {"worship_songs": [{"title": "곡 하나", "lines": ["옛 가사"], "provenance": gz},
                             {"title": "", "lines": ["x"], "provenance": gz},
                             {"title": "옛날 곡", "lines": ["출처 없는 OCR 시대 가사"]}]}  # pre-provenance: skipped
    new = {"worship_songs": [{"title": "곡 하나", "lines": ["새 가사"], "provenance": lib}],
           "worship_after_sermon": {"title": "설교후 곡", "lines": ["후 가사"], "provenance": gz}}
    (runs / "2026-10-04.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    (runs / "2026-10-11.json").write_text(json.dumps(new, ensure_ascii=False), encoding="utf-8")
    (runs / "2026-10-11.suggest.json").write_text("{}", encoding="utf-8")  # sidecar, not a run

    assert [(d, t) for d, t, _ in library.backfill_worship(runs)] == [
        ("2026-10-11", "곡 하나"), ("2026-10-11", "설교후 곡")]
    assert library.list_songs(library.WORSHIP_DIR) == []  # dry run
    library.backfill_worship(runs, write=True)
    assert library.load_song("곡-하나", library.WORSHIP_DIR)["lines"] == ["새 가사"]
    assert {s["title"] for s in library.list_songs(library.WORSHIP_DIR)} == {"곡 하나", "설교후 곡"}
