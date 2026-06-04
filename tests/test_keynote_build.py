"""Tests for worship_deck.keynote.build — AppleScript-driven Keynote primitives."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from worship_deck.bible.verses import Verse
from worship_deck.keynote import build as B
from worship_deck.keynote.build import (
    _chunk_verses,
    delete_slides,
    duplicate_slide,
    fill_verse_slides,
    read_verse_boxes,
    save_draft,
    set_date_slides,
    set_verse_slide,
)

# Body-box geometry from master.key (width, height), used to drive the chunk model in tests.
_CTW_KO_BOX, _CTW_EN_BOX = (1844, 544), (1836, 298)   # call-to-worship (slide 48)
_SERMON_KO_BOX, _SERMON_EN_BOX = (1837, 533), (1822, 332)  # sermon (slide 129)

# ---------------------------------------------------------------------------
# save_draft — mocked osascript (CI-safe, no Mac)
# ---------------------------------------------------------------------------


class _FakeCompleted:
    def __init__(self, returncode: int = 0, stderr: str = "", stdout: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout


def test_save_draft_invokes_osascript_and_makes_drafts_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict = {}

    def fake_run(cmd: list[str], **kw: object) -> _FakeCompleted:
        captured["cmd"] = cmd
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    out = tmp_path / "drafts" / "draft-2026-06-02.key"  # parent does not exist yet
    result = save_draft("template.key", str(out))

    assert result == str(out)
    assert out.parent.is_dir()  # save_draft created the drafts dir
    assert captured["cmd"][0] == "osascript"
    assert captured["cmd"][1] == str(B._SAVE_DRAFT)
    assert captured["cmd"][2:] == ["template.key", str(out)]


def test_save_draft_raises_on_nonzero_returncode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: _FakeCompleted(returncode=1, stderr="boom")
    )
    with pytest.raises(RuntimeError, match="save_draft.applescript failed: boom"):
        save_draft("template.key", str(tmp_path / "draft.key"))


def test_save_draft_raises_when_osascript_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*a: object, **kw: object) -> None:
        raise FileNotFoundError("osascript")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(RuntimeError, match="needs macOS"):
        save_draft("template.key", str(tmp_path / "draft.key"))


# ---------------------------------------------------------------------------
# duplicate_slide — mocked osascript (CI-safe, no Mac)
# ---------------------------------------------------------------------------


def test_duplicate_slide_passes_args_and_returns_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def fake_run(cmd: list[str], **kw: object) -> _FakeCompleted:
        captured["cmd"] = cmd
        return _FakeCompleted(returncode=0, stdout="42\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    n = duplicate_slide("draft.key", 1, 3)

    assert n == 42  # osascript stdout parsed to int
    assert captured["cmd"] == ["osascript", str(B._DUPLICATE_SLIDE), "draft.key", "1", "3"]


# ---------------------------------------------------------------------------
# set_date_slides — mocked osascript (CI-safe, no Mac)
# ---------------------------------------------------------------------------


def test_set_date_slides_passes_args_and_returns_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def fake_run(cmd: list[str], **kw: object) -> _FakeCompleted:
        captured["cmd"] = cmd
        return _FakeCompleted(returncode=0, stdout="4\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    n = set_date_slides("draft.key", "2026년 6월 7일", "테스트 제목", "[테스트 1:1]")

    assert n == 4  # number of date slides updated
    assert captured["cmd"] == [
        "osascript",
        str(B._SET_DATE_SLIDES),
        "draft.key",
        "2026년 6월 7일",
        "테스트 제목",
        "[테스트 1:1]",
    ]


# ---------------------------------------------------------------------------
# _chunk_verses — pure function (CI-safe)
# ---------------------------------------------------------------------------


def test_chunk_verses_keeps_short_passage_together_in_tall_box() -> None:
    # 4 short sermon verses fit the tall sermon boxes on one slide.
    verses = [Verse(n, "짧은절", "short verse") for n in range(14, 18)]
    chunks = _chunk_verses(verses, ko_box=_SERMON_KO_BOX, en_box=_SERMON_EN_BOX)
    assert len(chunks) == 1


def test_chunk_verses_spills_when_short_box_overflows() -> None:
    # The call-to-worship ESV box is short (h=298); long ESV verses must spill to >1 slide
    # rather than shrink below the floor.
    verses = [Verse(n, "형제가 연합하여 동거함이", "It is like the precious oil " * 4) for n in range(1, 4)]
    chunks = _chunk_verses(verses, ko_box=_CTW_KO_BOX, en_box=_CTW_EN_BOX)
    assert len(chunks) >= 2
    assert [v.number for c in chunks for v in c] == [1, 2, 3]  # order preserved, none dropped


def test_chunk_verses_giant_verse_stands_alone() -> None:
    verses = [Verse(1, "짧다", "short"), Verse(2, "긴" * 200, "long " * 200)]
    chunks = _chunk_verses(verses, ko_box=_SERMON_KO_BOX, en_box=_SERMON_EN_BOX)
    assert [len(c) for c in chunks] == [1, 1]


# ---------------------------------------------------------------------------
# set_verse_slide — mocked osascript (CI-safe, no Mac)
# ---------------------------------------------------------------------------


def test_set_verse_slide_passes_args(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_run(cmd: list[str], **kw: object) -> _FakeCompleted:
        captured["cmd"] = cmd
        return _FakeCompleted(returncode=0, stdout="ok\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = set_verse_slide(
        "draft.key", 48, "[시 133:1-3, 개역한글]", "1. 가", "[Psalms 133:1-3, ESV]", "1. a"
    )

    assert result == "ok"
    assert captured["cmd"] == [
        "osascript",
        str(B._SET_VERSE_SLIDE),
        "draft.key",
        "48",
        "[시 133:1-3, 개역한글]",
        "1. 가",
        "[Psalms 133:1-3, ESV]",
        "1. a",
    ]


def test_read_verse_boxes_parses_dimensions(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_run(cmd: list[str], **kw: object) -> _FakeCompleted:
        captured["cmd"] = cmd
        return _FakeCompleted(returncode=0, stdout="1844 544\n1836 298\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    ko_box, en_box = read_verse_boxes("draft.key", 48)

    assert ko_box == (1844, 544)
    assert en_box == (1836, 298)
    assert captured["cmd"] == ["osascript", str(B._READ_VERSE_BOXES), "draft.key", "48"]


def test_delete_slides_passes_args_and_returns_count(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_run(cmd: list[str], **kw: object) -> _FakeCompleted:
        captured["cmd"] = cmd
        return _FakeCompleted(returncode=0, stdout="167\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    n = delete_slides("draft.key", 132, 3)

    assert n == 167
    assert captured["cmd"] == ["osascript", str(B._DELETE_SLIDES), "draft.key", "132", "3"]


# ---------------------------------------------------------------------------
# Live integration — real Keynote; skipped without a Mac + TEMPLATE_KEY
# ---------------------------------------------------------------------------


def _on_canvas_text(key_path: str, slide_index: int) -> str:
    """Read the concatenated on-canvas text-item contents of one slide (Mac-only helper)."""
    script = (
        'on run argv\n'
        'tell application "Keynote"\n'
        "  activate\n"
        "  set d to open (POSIX file (item 1 of argv))\n"
        "  set s to slide ((item 2 of argv) as integer) of d\n"
        '  set out to ""\n'
        "  repeat with t in (text items of s)\n"
        "    set p to position of t\n"
        "    if (item 1 of p) is not 0 or (item 2 of p) is not 0 then\n"
        '      set out to out & ((object text of t) as text) & linefeed\n'
        "    end if\n"
        "  end repeat\n"
        "  close d saving no\n"
        "  return out\n"
        "end tell\n"
        "end run\n"
    )
    return subprocess.run(
        ["osascript", "-e", script, key_path, str(slide_index)],
        capture_output=True,
        text=True,
        timeout=120,
    ).stdout


@pytest.mark.local_only
def test_save_draft_live_produces_file(real_template_key: Path, tmp_path: Path) -> None:
    """Open the real template in Keynote and confirm a draft .key is written."""
    out = tmp_path / "draft-2026-06-02.key"
    save_draft(str(real_template_key), str(out))
    assert out.exists()  # .key is a package; exists() covers file or bundle


@pytest.mark.local_only
def test_duplicate_slide_live_adds_exactly_n(real_template_key: Path, tmp_path: Path) -> None:
    """Each duplicate_slide call must grow the deck by exactly N slides."""
    draft = tmp_path / "draft.key"
    save_draft(str(real_template_key), str(draft))
    c1 = duplicate_slide(str(draft), 1, 3)
    c2 = duplicate_slide(str(draft), 1, 2)
    assert c2 - c1 == 2  # second call added exactly 2 (self-contained, no fixed baseline)


@pytest.mark.local_only
def test_set_date_slides_live_swaps_text_and_keeps_static(
    real_template_key: Path, tmp_path: Path
) -> None:
    """Sets date/title/ref on the 4 date slides; static closing wording stays intact."""
    draft = tmp_path / "draft.key"
    save_draft(str(real_template_key), str(draft))

    n = set_date_slides(str(draft), "2026년 6월 7일", "테스트 제목", "[테스트 1:1]")
    assert n == 4  # two intro + two ending date slides

    intro = _on_canvas_text(str(draft), 1)  # intro 1부
    assert "2026년 6월 7일" in intro
    assert "테스트 제목" in intro
    assert "[테스트 1:1]" in intro

    ending = _on_canvas_text(str(draft), 167)  # ending 1부
    assert "2026년 6월 7일" in ending  # new date swapped in
    assert "예배를 마칩니다" in ending  # static closing wording preserved


@pytest.mark.local_only
def test_fill_verse_slides_live_fills_call_to_worship(
    real_template_key: Path, tmp_path: Path
) -> None:
    """Fill the 예배의 부름 verse slide (48); first chunk holds verse 1, junk stays off-canvas."""
    draft = tmp_path / "draft.key"
    save_draft(str(real_template_key), str(draft))

    verses = [
        Verse(1, "형제가 연합하여 동거함이", "Behold, how good and pleasant it is"),
        Verse(2, "머리에 있는 보배로운 기름이", "It is like the precious oil on the head"),
        Verse(3, "헐몬의 이슬이 시온의 산들에", "It is like the dew of Hermon"),
    ]
    kr_label, en_label = "[시 133:1-3, 개역한글]", "[Psalms 133:1-3, ESV]"

    n = fill_verse_slides(str(draft), 48, kr_label, en_label, verses, existing_count=1)
    assert n >= 1

    text = _on_canvas_text(str(draft), 48)  # first chunk
    assert kr_label in text
    assert en_label in text
    assert "1. 형제가 연합하여 동거함이" in text
    assert "1. Behold, how good and pleasant it is" in text
    assert "감사함으로 여호와께" not in text  # off-canvas {0,0} junk stays off-canvas


@pytest.mark.local_only
def test_fill_verse_slides_live_resizes_sermon_no_leftover(
    real_template_key: Path, tmp_path: Path
) -> None:
    """Sermon block is 4 template slides (129-132); filling fewer chunks must trim the surplus
    so no leftover 눅 verse slide remains right after the section."""
    draft = tmp_path / "draft.key"
    save_draft(str(real_template_key), str(draft))

    # Short verses → the tall sermon boxes pack several per slide → fewer than 4 chunks.
    verses = [Verse(n, f"{n}절 본문", f"verse {n} text") for n in range(14, 25)]
    kr_label, en_label = "[눅 22:14-24, 개역한글]", "[Luke 22:14-24, ESV]"

    n = fill_verse_slides(str(draft), 129, kr_label, en_label, verses, existing_count=4)
    assert n < 4  # packed into fewer slides than the template had

    for i in range(n):  # filled section slides carry the label
        assert kr_label in _on_canvas_text(str(draft), 129 + i)
    # the slide immediately after the resized section is no longer a 눅 verse slide
    assert "[눅" not in _on_canvas_text(str(draft), 129 + n)
