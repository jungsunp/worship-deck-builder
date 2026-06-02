"""Tests for worship_deck.keynote.build — AppleScript-driven Keynote primitives."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from worship_deck.keynote import build as B
from worship_deck.keynote.build import duplicate_slide, save_draft, set_date_slides

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
