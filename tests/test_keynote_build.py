"""Tests for worship_deck.keynote.build — AppleScript-driven Keynote primitives."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from worship_deck.keynote import build as B
from worship_deck.keynote.build import save_draft

# ---------------------------------------------------------------------------
# save_draft — mocked osascript (CI-safe, no Mac)
# ---------------------------------------------------------------------------


class _FakeCompleted:
    def __init__(self, returncode: int = 0, stderr: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr


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
    with pytest.raises(RuntimeError, match="Keynote save failed: boom"):
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
# Live integration — real Keynote; skipped without a Mac + TEMPLATE_KEY
# ---------------------------------------------------------------------------


@pytest.mark.local_only
def test_save_draft_live_produces_file(real_template_key: Path, tmp_path: Path) -> None:
    """Open the real template in Keynote and confirm a draft .key is written."""
    out = tmp_path / "draft-2026-06-02.key"
    save_draft(str(real_template_key), str(out))
    assert out.exists()  # .key is a package; exists() covers file or bundle
