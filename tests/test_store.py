"""Tests for worship_deck.store — per-run ServiceData JSON persistence."""

from __future__ import annotations

import pytest

from worship_deck import store
from worship_deck.parse import ServiceData


@pytest.fixture(autouse=True)
def _runs_dir(tmp_path, monkeypatch):
    """Redirect the store to a tmp dir (mirrors test_web patching INBOX_DIR)."""
    monkeypatch.setattr(store, "RUNS_DIR", tmp_path / "runs")


def _sample() -> ServiceData:
    return ServiceData(
        date="2026년 5월 31일",
        worship_order=[{"part": "찬 양", "title": "주 은혜임을", "leader": "다함께", "ref": ""}],
        announcements=["새가족 환영", "여름 수련회 안내"],
        call_to_worship_ref="시 100:1-3",
        sermon_title="다시 사신 주",
        sermon_ref="눅 24:1-12",
        offering_hymn_number="70",
        offering_hymn_title="피난처 있으니",
    )


def test_round_trip() -> None:
    data = _sample()
    store.save("2026-05-31", data)
    assert store.load("2026-05-31") == data


def test_edit_persists() -> None:
    store.save("2026-05-31", _sample())
    data = store.load("2026-05-31")
    data.offering_hymn_verses = [1, 2]
    store.save("2026-05-31", data)
    assert store.load("2026-05-31").offering_hymn_verses == [1, 2]


def test_korean_text_preserved() -> None:
    path = store.save("2026-05-31", _sample())
    # ensure_ascii=False → raw Hangul on disk, not \uXXXX escapes
    assert "피난처 있으니" in path.read_text(encoding="utf-8")


def test_unknown_keys_ignored() -> None:
    path = store.path_for("2026-05-31")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"date": "2026년 5월 31일", "future_field": [1, 2]}', encoding="utf-8")
    loaded = store.load("2026-05-31")
    assert loaded.date == "2026년 5월 31일"


def test_missing_run() -> None:
    assert store.exists("2026-05-31") is False
    with pytest.raises(FileNotFoundError):
        store.load("2026-05-31")


@pytest.mark.parametrize("bad", ["2026/5/31", "../etc/passwd", "2026-5-31", ""])
def test_bad_date_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        store.path_for(bad)
