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
    duplicate_block,
    duplicate_slide,
    fill_announcement_slides,
    fill_song_slides,
    fill_verse_slides,
    fill_worship_songs,
    place_image,
    read_verse_boxes,
    save_draft,
    set_announcement_slide,
    set_date_slides,
    set_sermon_title_slide,
    set_slide_text,
    set_verse_slide,
)
from worship_deck.lyrics.transcribe import Song, chunk

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


def test_duplicate_block_passes_args_and_returns_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def fake_run(cmd: list[str], **kw: object) -> _FakeCompleted:
        captured["cmd"] = cmd
        return _FakeCompleted(returncode=0, stdout="50\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    n = duplicate_block("draft.key", 6, 3, 8, 2)

    assert n == 50
    assert captured["cmd"] == ["osascript", str(B._DUPLICATE_BLOCK), "draft.key", "6", "3", "8", "2"]


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
# set_slide_text / fill_song_slides — mocked (CI-safe, no Mac)
# ---------------------------------------------------------------------------


def test_set_slide_text_passes_args(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_run(cmd: list[str], **kw: object) -> _FakeCompleted:
        captured["cmd"] = cmd
        return _FakeCompleted(returncode=0, stdout="ok\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = set_slide_text("draft.key", 8, "첫째 줄\n둘째 줄")

    assert result == "ok"
    assert captured["cmd"] == [
        "osascript",
        str(B._SET_SLIDE_TEXT),
        "draft.key",
        "8",
        "첫째 줄\n둘째 줄",
    ]


def test_set_sermon_title_slide_passes_args(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_run(cmd: list[str], **kw: object) -> _FakeCompleted:
        captured["cmd"] = cmd
        return _FakeCompleted(returncode=0, stdout="ok\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = set_sermon_title_slide("draft.key", 134, "믿음의 경주", "[히 12:1-2]")

    assert result == "ok"
    assert captured["cmd"] == [
        "osascript",
        str(B._SET_SERMON_TITLE),
        "draft.key",
        "134",
        "믿음의 경주",
        "[히 12:1-2]",
    ]


# ---------------------------------------------------------------------------
# place_image — mocked (CI-safe, no Mac)
# ---------------------------------------------------------------------------


def test_place_image_passes_args(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_run(cmd: list[str], **kw: object) -> _FakeCompleted:
        captured["cmd"] = cmd
        return _FakeCompleted(returncode=0, stdout="ok\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = place_image("draft.key", 5, "/tmp/slide-1.png")

    assert result == "ok"
    assert captured["cmd"] == [
        "osascript",
        str(B._PLACE_IMAGE),
        "draft.key",
        "5",
        "/tmp/slide-1.png",
    ]


def test_place_image_raises_on_nonzero_returncode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: _FakeCompleted(returncode=1, stderr="boom")
    )
    with pytest.raises(RuntimeError, match="place_image.applescript failed: boom"):
        place_image("draft.key", 5, "/tmp/slide-1.png")


def _mock_song_primitives(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Record fill_song_slides' Keynote primitive calls instead of running osascript."""
    calls: dict = {"set": [], "duplicate": None, "delete": None}
    monkeypatch.setattr(B, "set_slide_text", lambda k, i, t: calls["set"].append((i, t)))
    monkeypatch.setattr(B, "duplicate_slide", lambda k, i, n: calls.__setitem__("duplicate", (i, n)))
    monkeypatch.setattr(B, "delete_slides", lambda k, i, n: calls.__setitem__("delete", (i, n)))
    return calls


def test_fill_song_slides_duplicates_when_chunks_exceed_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _mock_song_primitives(monkeypatch)
    song = Song(title="제목", lines=["1", "2", "3", "4", "5"])  # 5 lines -> 3 chunks of <=2

    n = fill_song_slides("k", 7, song, existing_lyric_count=1)

    assert n == 4  # 1 title + 3 lyric slides
    assert calls["duplicate"] == (8, 2)  # first_lyric=8, add 2 to reach 3
    assert calls["delete"] is None
    # title set first, then each lyric chunk at consecutive indices
    assert calls["set"] == [(7, "제목"), (8, "1\n2"), (9, "3\n4"), (10, "5")]


def test_fill_song_slides_trims_when_template_has_surplus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _mock_song_primitives(monkeypatch)
    song = Song(title="제목", lines=["1", "2", "3", "4", "5"])  # 3 chunks

    n = fill_song_slides("k", 7, song, existing_lyric_count=4)

    assert n == 4
    assert calls["delete"] == (11, 1)  # trim the one surplus slide at first_lyric+target
    assert calls["duplicate"] is None
    assert [i for i, _ in calls["set"]] == [7, 8, 9, 10]


def test_fill_song_slides_empty_lyrics_leaves_title_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _mock_song_primitives(monkeypatch)
    song = Song(title="제목", lines=[])

    n = fill_song_slides("k", 7, song, existing_lyric_count=1)

    assert n == 1  # title slide only
    assert calls["delete"] == (8, 1)  # all template lyric slides trimmed
    assert calls["duplicate"] is None
    assert calls["set"] == [(7, "제목")]  # only the title is set


# ---------------------------------------------------------------------------
# fill_worship_songs — mocked primitives (CI-safe, no Mac)
# ---------------------------------------------------------------------------


def _mock_worship_primitives(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Record fill_worship_songs' orchestration of delete/duplicate_block/fill_song_slides."""
    calls: dict = {"delete": None, "dup_block": [], "fill": []}
    monkeypatch.setattr(B, "delete_slides", lambda k, i, n: calls.__setitem__("delete", (i, n)))
    monkeypatch.setattr(
        B, "duplicate_block", lambda k, a, b, c, d: calls["dup_block"].append((a, b, c, d))
    )

    def fake_fill(k: str, idx: int, song: Song, existing_lyric_count: int = 1) -> int:
        calls["fill"].append((idx, song.title))
        return 1 + len(chunk(song.lines))  # 1 title + L lyric slides

    monkeypatch.setattr(B, "fill_song_slides", fake_fill)
    return calls


def test_fill_worship_songs_three_song_medley(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _mock_worship_primitives(monkeypatch)
    songs = [
        Song(title="주 은혜임을", lines=["1", "2", "3", "4"]),  # 2 lyric slides
        Song(title="주님 다시 오실 때까지", lines=["1", "2"]),  # 1 lyric slide
        Song(title="마라나타", lines=["1", "2"]),  # 1 lyric slide
    ]

    # worship range = master slides 6..46 (start_index=6, section_len=41)
    n = fill_worship_songs("k", 6, 41, songs)

    # collapse to the 3-slide seed unit; drop the other 38 slides in the range
    assert calls["delete"] == (9, 38)
    # fan the seed unit to 3 (2 extra copies after the seed lyric @8), then a trailing blank
    assert calls["dup_block"] == [(6, 3, 8, 2), (6, 1, 14, 1)]
    # fills run back-to-front; title indices are 6 + 3*i + 1 for i = 2, 1, 0
    assert calls["fill"] == [(13, "마라나타"), (10, "주님 다시 오실 때까지"), (7, "주 은혜임을")]
    # 3 units (blank+title+lyric) + trailing blank, plus the extra lyric slide song 1 expands
    assert n == 11


def test_fill_worship_songs_single_song_skips_fan_out(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _mock_worship_primitives(monkeypatch)
    songs = [Song(title="마라나타", lines=["1", "2"])]

    n = fill_worship_songs("k", 6, 41, songs)

    assert calls["delete"] == (9, 38)
    # only the trailing-blank copy — no fan-out for a single song
    assert calls["dup_block"] == [(6, 1, 8, 1)]
    assert calls["fill"] == [(7, "마라나타")]
    assert n == 4  # blank + title + 1 lyric + trailing blank


def test_fill_worship_songs_empty_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _mock_worship_primitives(monkeypatch)

    n = fill_worship_songs("k", 6, 41, [])

    assert n == 0
    assert calls["delete"] is None
    assert calls["dup_block"] == []
    assert calls["fill"] == []


# ---------------------------------------------------------------------------
# fill_announcement_slides — mocked primitives (CI-safe, no Mac)
# ---------------------------------------------------------------------------


def test_set_announcement_slide_passes_args(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_run(cmd: list[str], **kw: object) -> _FakeCompleted:
        captured["cmd"] = cmd
        return _FakeCompleted(returncode=0, stdout="ok\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = set_announcement_slide("draft.key", 117, "1. 제목\n\n   상세 내용")

    assert result == "ok"
    assert captured["cmd"] == [
        "osascript",
        str(B._SET_ANNOUNCEMENT_SLIDE),
        "draft.key",
        "117",
        "1. 제목\n\n   상세 내용",
    ]


def _mock_announce_primitives(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Record fill_announcement_slides' Keynote primitive calls instead of running osascript."""
    calls: dict = {"set": [], "duplicate": None, "delete": None}
    monkeypatch.setattr(B, "set_announcement_slide", lambda k, i, t: calls["set"].append((i, t)))
    monkeypatch.setattr(B, "duplicate_slide", lambda k, i, n: calls.__setitem__("duplicate", (i, n)))
    monkeypatch.setattr(B, "delete_slides", lambda k, i, n: calls.__setitem__("delete", (i, n)))
    return calls


def test_fill_announcement_slides_duplicates_when_items_exceed_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _mock_announce_primitives(monkeypatch)

    n = fill_announcement_slides("k", 117, ["1. 첫째", "2. 둘째", "3. 셋째"], existing_count=1)

    assert n == 3
    assert calls["duplicate"] == (117, 2)  # add 2 to reach 3
    assert calls["delete"] is None
    assert calls["set"] == [(117, "1. 첫째"), (118, "2. 둘째"), (119, "3. 셋째")]


def test_fill_announcement_slides_trims_when_template_has_surplus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _mock_announce_primitives(monkeypatch)

    n = fill_announcement_slides("k", 117, ["1. 첫째", "2. 둘째"], existing_count=5)

    assert n == 2
    assert calls["delete"] == (119, 3)  # trim 3 surplus at start+target
    assert calls["duplicate"] is None
    assert calls["set"] == [(117, "1. 첫째"), (118, "2. 둘째")]


def test_fill_announcement_slides_empty_list_trims_whole_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _mock_announce_primitives(monkeypatch)

    n = fill_announcement_slides("k", 117, [], existing_count=5)

    assert n == 0
    assert calls["delete"] == (117, 5)  # whole block trimmed
    assert calls["duplicate"] is None
    assert calls["set"] == []  # nothing to set


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


@pytest.mark.local_only
def test_set_sermon_title_slide_live_sets_title_and_ref(
    real_template_key: Path, tmp_path: Path
) -> None:
    """Slide 134 has a white title box + a gold scripture-ref box (the bracketed one). Both must
    take their own text, and last week's reference must be gone — not duplicated across both (#90)."""
    draft = tmp_path / "draft.key"
    save_draft(str(real_template_key), str(draft))

    assert set_sermon_title_slide(str(draft), 134, "믿음의 경주", "[히 12:1-2]") == "ok"

    text = _on_canvas_text(str(draft), 134)
    assert "믿음의 경주" in text  # title box set
    assert "[히 12:1-2]" in text  # ref box set
    assert "[눅" not in text  # last week's reference is gone, not left in the gold box


@pytest.mark.local_only
def test_fill_song_slides_live_fills_title_and_trims_leftover(
    real_template_key: Path, tmp_path: Path
) -> None:
    """Song 1 in the template is a title slide (7) + 10 lyric slides (8-17). Filling a 6-line
    song (3 chunks) must set the title, fill 3 lyric slides, and trim the 7 surplus so no
    leftover template lyric slide remains right after the section."""
    draft = tmp_path / "draft.key"
    save_draft(str(real_template_key), str(draft))

    song = Song(
        title="테스트 찬양",
        lines=["첫째 줄", "둘째 줄", "셋째 줄", "넷째 줄", "다섯째 줄", "여섯째 줄"],
    )

    n = fill_song_slides(str(draft), 7, song, existing_lyric_count=10)
    assert n == 4  # 1 title + 3 lyric slides

    assert "테스트 찬양" in _on_canvas_text(str(draft), 7)  # title slide set
    assert "첫째 줄" in _on_canvas_text(str(draft), 8) and "둘째 줄" in _on_canvas_text(str(draft), 8)
    assert "셋째 줄" in _on_canvas_text(str(draft), 9)
    assert "다섯째 줄" in _on_canvas_text(str(draft), 10)
    # the slide right after the resized lyric block holds none of this song's lyrics (no leftover)
    assert "줄" not in _on_canvas_text(str(draft), 11)


@pytest.mark.local_only
def test_fill_announcement_slides_live_resizes_no_leftover(
    real_template_key: Path, tmp_path: Path
) -> None:
    """The 교회소식 block is 5 item slides (117-121). Filling 3 items must set each, trim the 2
    surplus, and leave none of the sample text on the slide right after the block."""
    draft = tmp_path / "draft.key"
    save_draft(str(real_template_key), str(draft))

    items = [
        "1. 첫째 소식\n\n   첫째 상세 내용입니다.",
        "2. 둘째 소식\n\n   둘째 상세 내용입니다.",
        "3. 셋째 소식\n\n   셋째 상세 내용입니다.",
    ]
    n = fill_announcement_slides(str(draft), 117, items, existing_count=5)
    assert n == 3

    s117 = _on_canvas_text(str(draft), 117)
    assert "1. 첫째 소식" in s117 and "첫째 상세 내용입니다." in s117  # title + detail both set
    assert "2. 둘째 소식" in _on_canvas_text(str(draft), 118)
    assert "3. 셋째 소식" in _on_canvas_text(str(draft), 119)
    # the slide right after the resized block carries none of the sample announcement text
    assert "소식" not in _on_canvas_text(str(draft), 120)


def _last_image_frame(
    key_path: str, slide_index: int
) -> tuple[int, float, float, float, float, float, float]:
    """Read (image_count, x, y, w, h, doc_w, doc_h) for a slide's last image (Mac-only).

    Folds the image frame and the document size into one read so the caller can compare them
    without reopening the deck."""
    script = (
        "on run argv\n"
        'tell application "Keynote"\n'
        "  activate\n"
        "  set d to open (POSIX file (item 1 of argv))\n"
        "  set s to slide ((item 2 of argv) as integer) of d\n"
        "  set n to count of images of s\n"
        "  set img to last image of s\n"
        "  set p to position of img\n"  # set first, then index (specifier gotcha)
        "  set px to item 1 of p\n"
        "  set py to item 2 of p\n"
        "  set w to width of img\n"
        "  set h to height of img\n"
        "  set dw to width of d\n"
        "  set dh to height of d\n"
        "  close d saving no\n"
        "  return (n as text) & \" \" & (px as text) & \" \" & (py as text) & \" \" "
        "& (w as text) & \" \" & (h as text) & \" \" & (dw as text) & \" \" & (dh as text)\n"
        "end tell\n"
        "end run\n"
    )
    out = subprocess.run(
        ["osascript", "-e", script, key_path, str(slide_index)],
        capture_output=True,
        text=True,
        timeout=120,
    ).stdout
    n, px, py, w, h, dw, dh = out.split()
    return int(n), float(px), float(py), float(w), float(h), float(dw), float(dh)


@pytest.mark.local_only
def test_place_image_live_covers_slide_centered(
    real_template_key: Path, tmp_path: Path
) -> None:
    """Placing a PNG must add an image that covers the slide edge-to-edge, centered (aspect-fill).

    Uses a 4:3 PNG against the 16:9 deck so the image overflows on one axis: it must reach the
    slide on both axes (cover), exactly match the slide on the constraining axis, and be centered
    so the overflow is split evenly (negative offset on the overflowing axis)."""
    from PIL import Image

    png = tmp_path / "sheet.png"
    Image.new("RGB", (400, 300), "white").save(png)  # aspect deliberately != deck's

    draft = tmp_path / "draft.key"
    save_draft(str(real_template_key), str(draft))

    assert place_image(str(draft), 1, str(png)) == "ok"

    n, px, py, w, h, dw, dh = _last_image_frame(str(draft), 1)
    assert n >= 1  # an image was added
    assert w >= dw - 1 and h >= dh - 1  # covers the slide on both axes (no margins)
    assert abs(w - dw) < 1 or abs(h - dh) < 1  # exactly meets the slide on the constraining axis
    assert abs(px - (dw - w) / 2) < 1 and abs(py - (dh - h) / 2) < 1  # centered (overflow split)
