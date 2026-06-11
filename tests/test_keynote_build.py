"""Tests for worship_deck.keynote.build — AppleScript-driven Keynote primitives."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from worship_deck.bible.verses import Verse
from worship_deck.keynote import build as B
from worship_deck.keynote.build import (
    _chunk_verses,
    _fit_title,
    _wrap_balanced,
    build,
    delete_slides,
    duplicate_block,
    duplicate_slide,
    fill_announcement_slides,
    fill_choir_slides,
    fill_confession_slides,
    fill_hymn_slides,
    fill_song_slides,
    fill_verse_slides,
    fill_worship_songs,
    finalize_draft,
    hymn_image_block,
    place_image,
    read_title_box,
    read_verse_boxes,
    save_draft,
    set_announcement_slide,
    set_call_to_worship_ref,
    set_choir_title,
    set_confession_title,
    set_date_slides,
    set_offering_hymn_title_slide,
    set_sermon_ref_slide,
    set_sermon_title_slide,
    set_slide_text,
    set_verse_slide,
)
from worship_deck.lyrics.transcribe import Song, chunk
from worship_deck.parse.bulletin import ServiceData

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
# finalize_draft — mocked osascript (CI-safe, no Mac)
# ---------------------------------------------------------------------------


def test_finalize_draft_passes_args_and_returns_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """finalize_draft saves the open front document once (#117) and passes out_key vestigially."""
    captured: dict = {}

    def fake_run(cmd: list[str], **kw: object) -> _FakeCompleted:
        captured["cmd"] = cmd
        return _FakeCompleted(returncode=0, stdout="ok\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert finalize_draft("out.key") == "out.key"
    assert captured["cmd"] == ["osascript", str(B._FINALIZE), "out.key"]


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


def test_chunk_verses_matches_ideal_slide_46() -> None:
    # Calibration anchor (#115): the operator-approved 2026-06-07 deck shows exactly these two
    # verses on one 예배의 부름 slide (slide 46) at the target fonts — the ideal density. The
    # model must reproduce that packing, and must spill once a third comparable verse is added.
    verses = [
        Verse(
            19,
            "지금부터는 아버지의 아들이라 일컬음을 감당치 못하겠나이다 나를 품꾼의 하나로 보소서 하리라 하고",
            "I am no longer worthy to be called your son. Treat me as one of your hired servants.",
        ),
        Verse(
            20,
            "이에 일어나서 아버지께 돌아 가니라 아직도 상거가 먼데 아버지가 저를 보고 측은히 여겨 달려가 목을 안고 입을 맞추니",
            "And he arose and came to his father. But while he was still a long way off, his "
            "father saw him and felt compassion, and ran and embraced him and kissed him.",
        ),
    ]
    assert len(_chunk_verses(verses, ko_box=_CTW_KO_BOX, en_box=_CTW_EN_BOX)) == 1
    assert len(_chunk_verses(verses + verses[:1], ko_box=_CTW_KO_BOX, en_box=_CTW_EN_BOX)) == 2


def test_fit_font_returns_target_for_fitting_chunk() -> None:
    assert B._fit_font(
        ["1. 짧은절"], _CTW_KO_BOX, B._CHAR_W_KO, B._LINE_H_KO, B._TARGET_FONT_KO, B._MIN_FONT_KO
    ) == B._TARGET_FONT_KO


def test_fit_font_shrinks_lone_giant_verse_to_fit() -> None:
    font = B._fit_font(
        ["1. " + "긴" * 160], _CTW_KO_BOX, B._CHAR_W_KO, B._LINE_H_KO,
        B._TARGET_FONT_KO, B._MIN_FONT_KO,
    )
    assert B._MIN_FONT_KO <= font < B._TARGET_FONT_KO


def test_fit_font_never_goes_below_floor() -> None:
    font = B._fit_font(
        ["1. " + "긴" * 2000], _CTW_KO_BOX, B._CHAR_W_KO, B._LINE_H_KO,
        B._TARGET_FONT_KO, B._MIN_FONT_KO,
    )
    assert font == B._MIN_FONT_KO


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
        str(B._TARGET_FONT_KO),  # explicit font (#115): consistent density across sections
        str(B._TARGET_FONT_EN),
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


def test_fill_sermon_extra_slides_inserts_reversed_at_fixed_anchors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#114: each extra ref seeds a copy of the pristine 129 verse slide after 134 and fills
    it at 135; refs run in REVERSE so the deck ends up in input order with fixed anchors.
    An empty passage (lookup failed at save) is skipped entirely."""
    calls: list[tuple] = []
    monkeypatch.setattr(
        B, "duplicate_block",
        lambda key, src, src_len, dest, times: calls.append(("dup", src, src_len, dest, times)),
    )
    monkeypatch.setattr(
        B, "fill_verse_slides",
        lambda key, idx, kr, en, verses, **kw: calls.append(
            ("fill", idx, kr, en, [v.number for v in verses], kw["existing_count"])
        ),
    )
    refs = ["요 3:16", "롬 8:1-4", "잘못된 구절"]
    passages = [
        [{"number": 16, "korean": "한", "english": "en"}],
        [{"number": 1, "korean": "한", "english": "en"}, {"number": 2, "korean": "한", "english": "en"}],
        [],  # skipped before any label parsing or slide op
    ]
    B.fill_sermon_extra_slides("deck.key", refs, passages)

    assert calls == [
        ("dup", 129, 1, 134, 1),
        ("fill", 135, "[롬 8:1-4, 개역한글]", "[Romans 8:1-4, ESV]", [1, 2], 1),
        ("dup", 129, 1, 134, 1),
        ("fill", 135, "[요 3:16, 개역한글]", "[John 3:16, ESV]", [16], 1),
    ]


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

    # read_title_box drives the wrap/shrink; stub it so the test stays CI-safe (no Keynote).
    monkeypatch.setattr(B, "read_title_box", lambda *a: (758, 326, 130))
    monkeypatch.setattr(subprocess, "run", fake_run)

    result = set_sermon_title_slide("draft.key", 134, "참된 예배", "[히 12:1-2]")

    assert result == "ok"
    # short title fits one line at the box's base font, so text is unwrapped and font is 130
    assert captured["cmd"] == [
        "osascript",
        str(B._SET_SERMON_TITLE),
        "draft.key",
        "134",
        "참된 예배",
        "[히 12:1-2]",
        "130",
    ]


def test_set_sermon_title_slide_wraps_and_shrinks_long_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def fake_run(cmd: list[str], **kw: object) -> _FakeCompleted:
        captured["cmd"] = cmd
        return _FakeCompleted(returncode=0, stdout="ok\n")

    monkeypatch.setattr(B, "read_title_box", lambda *a: (758, 326, 130))
    monkeypatch.setattr(subprocess, "run", fake_run)

    set_sermon_title_slide("draft.key", 134, "왜 그럼 그 때는 가만히 계셨을까?", "[삼상 5:1-12]")

    # title overflows one line, so it wraps to two balanced lines and the font shrinks below base
    wrapped, font = captured["cmd"][4], captured["cmd"][6]
    assert wrapped == "왜 그럼 그 때는\n가만히 계셨을까?"
    assert int(font) < 130


def test_set_call_to_worship_ref_passes_args(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_run(cmd: list[str], **kw: object) -> _FakeCompleted:
        captured["cmd"] = cmd
        return _FakeCompleted(returncode=0, stdout="ok\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = set_call_to_worship_ref("draft.key", 47, "눅 15:19-23")

    assert result == "ok"
    assert captured["cmd"] == [
        "osascript",
        str(B._SET_CTW_REF),
        "draft.key",
        "47",
        "[ 눅 15:19-23 ]",  # spaced brackets, matching the deck
    ]


def test_set_sermon_ref_slide_passes_args(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_run(cmd: list[str], **kw: object) -> _FakeCompleted:
        captured["cmd"] = cmd
        return _FakeCompleted(returncode=0, stdout="ok\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = set_sermon_ref_slide("draft.key", 127, "삼상 5:1-12")

    assert result == "ok"
    assert captured["cmd"] == [
        "osascript",
        str(B._SET_SERMON_REF),
        "draft.key",
        "127",
        "삼상 5:1-12",          # bare Korean ref box
        "[1 Samuel 5:1-12]",    # bracketed English ref box (ESV book name)
    ]


def test_read_title_box_parses_dimensions(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd: list[str], **kw: object) -> _FakeCompleted:
        return _FakeCompleted(returncode=0, stdout="758 326 130.0\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert read_title_box("draft.key", 134) == (758, 326, 130)


# _wrap_balanced / _fit_title — pure functions (CI-safe)

def test_wrap_balanced_two_lines_splits_evenly() -> None:
    assert _wrap_balanced("왜 그럼 그 때는 가만히 계셨을까?", 2) == ["왜 그럼 그 때는", "가만히 계셨을까?"]


def test_wrap_balanced_single_word_stays_one_line() -> None:
    assert _wrap_balanced("주기도문", 2) == ["주기도문"]


def test_fit_title_short_keeps_one_line_at_base_font() -> None:
    text, font = _fit_title("참된 예배", 758, 326, 130)
    assert text == "참된 예배"
    assert font == 130


def test_fit_title_long_wraps_to_two_lines_under_base() -> None:
    text, font = _fit_title("왜 그럼 그 때는 가만히 계셨을까?", 758, 326, 130)
    assert text == "왜 그럼 그 때는\n가만히 계셨을까?"
    # Shrunk from base but kept the LARGEST fitting font, so it stays bigger than the gold
    # scripture ref (84pt on master.key) — the title is the dominant element (#106 follow-up).
    assert 84 < font < 130


def test_set_offering_hymn_title_slide_passes_args(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_run(cmd: list[str], **kw: object) -> _FakeCompleted:
        captured["cmd"] = cmd
        return _FakeCompleted(returncode=0, stdout="ok\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = set_offering_hymn_title_slide("draft.key", 97, "455", "주님의 마음을 본받는 자")

    assert result == "ok"
    assert captured["cmd"] == [
        "osascript",
        str(B._SET_OFFERING_HYMN_TITLE),
        "draft.key",
        "97",
        "[ 주님의 마음을 본받는 자 ]",
        "(찬 455장)",
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
        "0",  # clear_existing off by default
    ]


def test_place_image_clear_existing_passes_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_run(cmd: list[str], **kw: object) -> _FakeCompleted:
        captured["cmd"] = cmd
        return _FakeCompleted(returncode=0, stdout="ok\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    place_image("draft.key", 5, "/tmp/slide-1.png", clear_existing=True)

    assert captured["cmd"][-1] == "1"  # delete existing images first


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
# set_choir_title / fill_choir_slides — mocked (CI-safe, no Mac)
# ---------------------------------------------------------------------------


def test_set_choir_title_passes_args(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_run(cmd: list[str], **kw: object) -> _FakeCompleted:
        captured["cmd"] = cmd
        return _FakeCompleted(returncode=0, stdout="ok\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = set_choir_title("draft.key", 77, "사랑은", "(윤학준 곡)")

    assert result == "ok"
    assert captured["cmd"] == [
        "osascript",
        str(B._SET_CHOIR_TITLE),
        "draft.key",
        "77",
        "사랑은",
        "(윤학준 곡)",
    ]


def _mock_choir_primitives(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Record fill_choir_slides' Keynote primitive calls instead of running osascript."""
    calls: dict = {"title": [], "lyric": [], "duplicate": None, "delete": None}
    monkeypatch.setattr(B, "set_choir_title", lambda k, i, t, c: calls["title"].append((i, t, c)))
    monkeypatch.setattr(B, "set_slide_text", lambda k, i, t: calls["lyric"].append((i, t)))
    monkeypatch.setattr(B, "duplicate_slide", lambda k, i, n: calls.__setitem__("duplicate", (i, n)))
    monkeypatch.setattr(B, "delete_slides", lambda k, i, n: calls.__setitem__("delete", (i, n)))
    return calls


def test_fill_choir_slides_duplicates_when_chunks_exceed_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _mock_choir_primitives(monkeypatch)
    song = Song(title="사랑은", lines=["1", "2", "3"], composer="윤학준 편곡")  # 3 lines -> 2 chunks

    n = fill_choir_slides("k", 77, song, title_count=2, existing_lyric_count=1)

    assert n == 4  # 2 title slides + 2 lyric chunks
    # both title slides get the same title; a bare composer is parenthesized for the credit
    assert calls["title"] == [(77, "사랑은", "(윤학준 편곡)"), (78, "사랑은", "(윤학준 편곡)")]
    assert calls["duplicate"] == (79, 1)  # first_lyric=79, add 1 to reach 2
    assert calls["delete"] is None
    assert calls["lyric"] == [(79, "1\n2"), (80, "3")]


def test_fill_choir_slides_trims_when_template_has_surplus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _mock_choir_primitives(monkeypatch)
    song = Song(title="사랑은", lines=["1", "2", "3"], composer="(윤학준 곡)")  # 2 chunks

    n = fill_choir_slides("k", 77, song, title_count=2, existing_lyric_count=17)

    assert n == 4
    # a composer that already carries its own parentheses is not double-wrapped
    assert calls["title"] == [(77, "사랑은", "(윤학준 곡)"), (78, "사랑은", "(윤학준 곡)")]
    assert calls["delete"] == (81, 15)  # trim 15 surplus slides at first_lyric+target (79+2)
    assert calls["duplicate"] is None
    assert [i for i, _ in calls["lyric"]] == [79, 80]


# ---------------------------------------------------------------------------
# set_confession_title / fill_confession_slides — mocked (CI-safe, no Mac)
# ---------------------------------------------------------------------------


def test_set_confession_title_passes_bracketed_title(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_run(cmd: list[str], **kw: object) -> _FakeCompleted:
        captured["cmd"] = cmd
        return _FakeCompleted(returncode=0, stdout="ok\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = set_confession_title("draft.key", 57, "주만 바라볼찌라")

    assert result == "ok"
    # the title line is formatted here to match the template's "[ <title> ]" style
    assert captured["cmd"] == [
        "osascript",
        str(B._SET_CONFESSION_TITLE),
        "draft.key",
        "57",
        "[ 주만 바라볼찌라 ]",
    ]


def test_fill_confession_slides_sets_divider_and_delegates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict = {"title": [], "fill": []}
    monkeypatch.setattr(
        B, "set_confession_title", lambda k, i, t: calls["title"].append((i, t))
    )

    def fake_fill(k: str, idx: int, song: Song, existing_lyric_count: int = 1) -> int:
        calls["fill"].append((idx, song.title, existing_lyric_count))
        return 1 + len(chunk(song.lines))  # 1 banner + L lyric slides

    monkeypatch.setattr(B, "fill_song_slides", fake_fill)
    song = Song(title="주만 바라볼찌라", lines=["1", "2", "3"])  # 3 lines -> 2 chunks

    n = fill_confession_slides("k", 57, song)

    assert calls["title"] == [(57, "주만 바라볼찌라")]  # divider gets the bare title (bracketed inside)
    # banner at divider+2 (58 is the blank separator); the template lyric block is 8 slides
    assert calls["fill"] == [(59, "주만 바라볼찌라", 8)]
    assert n == 6  # divider + blank + banner + 2 lyric chunks + trailing blank


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
# fill_hymn_slides — mocked primitives (CI-safe, no Mac)
# ---------------------------------------------------------------------------


def _mock_hymn_primitives(monkeypatch: pytest.MonkeyPatch, block: tuple[int, int]) -> dict:
    """Record fill_hymn_slides' Keynote primitive calls; stub the detected image block.

    `block` is the (first, last) image-slide run hymn_image_block would detect in the template —
    e.g. (99, 106) for an 8-page hymn after the section's two title/intro slides.
    """
    calls: dict = {"place": [], "duplicate": None, "delete": None}
    monkeypatch.setattr(B, "hymn_image_block", lambda k, s, *a: block)
    monkeypatch.setattr(
        B, "place_image",
        lambda k, i, p, *, clear_existing=False: calls["place"].append((i, p, clear_existing)),
    )
    monkeypatch.setattr(B, "duplicate_slide", lambda k, i, n: calls.__setitem__("duplicate", (i, n)))
    monkeypatch.setattr(B, "delete_slides", lambda k, i, n: calls.__setitem__("delete", (i, n)))
    return calls


def test_fill_hymn_slides_duplicates_when_images_exceed_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _mock_hymn_primitives(monkeypatch, block=(99, 106))  # 8 existing pages
    images = [f"slide-{i}.png" for i in range(1, 13)]  # 12 images

    n = fill_hymn_slides("k", 97, images)

    assert n == 12
    assert calls["duplicate"] == (99, 4)  # add 4 to reach 12, from the block's first slide
    assert calls["delete"] is None
    # placed from the block's first slide (title slides untouched), each replacing last week's page
    assert calls["place"] == [(99 + i, img, True) for i, img in enumerate(images)]


def test_fill_hymn_slides_trims_when_block_has_surplus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _mock_hymn_primitives(monkeypatch, block=(99, 106))  # 8 existing pages
    images = ["slide-1.png", "slide-2.png", "slide-3.png"]

    n = fill_hymn_slides("k", 97, images)

    assert n == 3
    assert calls["delete"] == (102, 5)  # trim 5 leftover pages at first+target
    assert calls["duplicate"] is None
    assert calls["place"] == [
        (99, "slide-1.png", True),
        (100, "slide-2.png", True),
        (101, "slide-3.png", True),
    ]


def test_fill_hymn_slides_raises_when_no_image_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_hymn_primitives(monkeypatch, block=(0, 0))  # no hymn pages detected

    with pytest.raises(RuntimeError, match="No 봉헌 hymn-image slides"):
        fill_hymn_slides("k", 97, ["slide-1.png"])


# ---------------------------------------------------------------------------
# Live integration — real Keynote; skipped without a Mac + TEMPLATE_KEY
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_keynote_before_live(request: pytest.FixtureRequest) -> None:
    """Clear stale open Keynote docs before each live test (#117); no-op for the mocked tests.

    Open-once/save-once means save_draft no longer closes its draft — it leaves it open as the
    `front document` that every primitive (and the read-back helpers below) mutate/read in place.
    So before each local_only test we close any doc left open by a prior test, mirroring build()'s
    own `_ensure_keynote_ready()` precondition, so save_draft's draft is the unambiguous front doc.
    """
    if request.node.get_closest_marker("local_only"):
        B._ensure_keynote_ready()


def _on_canvas_text(key_path: str, slide_index: int) -> str:
    """Read the concatenated on-canvas text-item contents of one slide (Mac-only helper).

    Reads the open `front document` (the draft save_draft left open) so it sees the build's
    in-place, not-yet-saved edits (#117); `key_path` is vestigial but kept for call-site symmetry.
    """
    script = (
        'on run argv\n'
        'tell application "Keynote"\n'
        "  set d to front document\n"
        "  set s to slide ((item 2 of argv) as integer) of d\n"
        '  set out to ""\n'
        "  repeat with t in (text items of s)\n"
        "    set p to position of t\n"
        "    if (item 1 of p) is not 0 or (item 2 of p) is not 0 then\n"
        '      set out to out & ((object text of t) as text) & linefeed\n'
        "    end if\n"
        "  end repeat\n"
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
def test_save_draft_binds_open_doc_to_draft_not_template(
    real_template_key: Path, tmp_path: Path
) -> None:
    """Regression (#98 fallout): after save_draft the open front document must be the DRAFT,
    not the template — every fill mutates this open doc in place, and a crash before finalize
    lets macOS autosave write it to disk. Bound to the draft that's harmless; the old
    template-bound behavior silently corrupted master.key on every crashed build.
    """
    draft = tmp_path / "draft.key"
    save_draft(str(real_template_key), str(draft))
    open_path = subprocess.run(
        ["osascript", "-e", 'tell application "Keynote" to return POSIX path of ((file of front document) as text)'],
        capture_output=True,
        text=True,
        timeout=120,
    ).stdout.strip()
    assert Path(open_path) == draft
    assert Path(open_path) != real_template_key


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

    # #115: the body font is set explicitly to the target so density matches across sections.
    script = (
        'tell application "Keynote"\n'
        "  set s to slide 48 of front document\n"
        "  repeat with i from 1 to (count of text items of s)\n"
        "    set t to text item i of s\n"
        "    set p to position of t\n"
        "    if (item 1 of p) is not 0 or (item 2 of p) is not 0 then\n"
        '      set txt to (object text of t) as text\n'
        '      if txt starts with "1. 형제가" then return (size of object text of t) as text\n'
        "    end if\n"
        "  end repeat\n"
        "end tell\n"
    )
    size = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True, timeout=120
    ).stdout.strip()
    assert size == f"{B._TARGET_FONT_KO}.0"


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
def test_set_offering_hymn_title_slide_live_sets_title_and_number(
    real_template_key: Path, tmp_path: Path
) -> None:
    """Slide 97 is one box of 3 paragraphs — a static "봉 헌" heading, the bracketed hymn title,
    then "(찬 N장)". The heading must survive while the title/number are replaced with this week's,
    and last week's number/title must be gone (#106)."""
    draft = tmp_path / "draft.key"
    save_draft(str(real_template_key), str(draft))

    assert set_offering_hymn_title_slide(str(draft), 97, "455", "주님의 마음을 본받는 자") == "ok"

    text = _on_canvas_text(str(draft), 97)
    assert "봉" in text  # static heading preserved
    assert "[ 주님의 마음을 본받는 자 ]" in text  # title paragraph set
    assert "(찬 455장)" in text  # number paragraph set
    assert "피난처" not in text  # last week's title is gone
    assert "70장" not in text  # last week's number is gone


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
def test_fill_choir_slides_live_fills_titles_composer_and_lyrics(
    real_template_key: Path, tmp_path: Path
) -> None:
    """The 성가대 block is 2 title slides (77-78) + 17 lyric slides (79-95). Filling a 3-line song
    (2 chunks) must set the song title + composer on both title slides (keeping slide 77's static
    '성가대 찬양' heading), fill 2 lyric slides, and trim the 15 surplus so none remain after."""
    draft = tmp_path / "draft.key"
    save_draft(str(real_template_key), str(draft))

    song = Song(title="테스트 성가", lines=["첫째 줄", "둘째 줄", "셋째 줄"], composer="테스트 곡")

    n = fill_choir_slides(str(draft), 77, song, existing_lyric_count=17)
    assert n == 4  # 2 title slides + 2 lyric chunks

    s77, s78 = _on_canvas_text(str(draft), 77), _on_canvas_text(str(draft), 78)
    assert "테스트 성가" in s77 and "(테스트 곡)" in s77 and "성가대 찬양" in s77  # heading kept
    assert "테스트 성가" in s78 and "(테스트 곡)" in s78
    assert "첫째 줄" in _on_canvas_text(str(draft), 79) and "둘째 줄" in _on_canvas_text(str(draft), 79)
    assert "셋째 줄" in _on_canvas_text(str(draft), 80)
    # the slide right after the resized lyric block holds none of this song's lyrics (no leftover)
    assert "줄" not in _on_canvas_text(str(draft), 81)


@pytest.mark.local_only
def test_fill_confession_slides_live_fills_divider_banner_and_lyrics(
    real_template_key: Path, tmp_path: Path
) -> None:
    """The 고백의 찬양 block is divider (57) + blank + title banner (59) + 8 lyric slides (60-67)
    + trailing blank (68). Filling a 3-line song (2 chunks) must keep slide 57's static
    '고백의 찬양' heading, set its bracketed title, set the banner, fill 2 lyric slides, and trim
    the 6 surplus so the trailing blank (now slide 62) carries no leftover lyrics."""
    draft = tmp_path / "draft.key"
    save_draft(str(real_template_key), str(draft))

    song = Song(title="테스트 고백", lines=["첫째 줄", "둘째 줄", "셋째 줄"])

    n = fill_confession_slides(str(draft), 57, song, existing_lyric_count=8)
    assert n == 6  # divider + blank + banner + 2 lyric chunks + trailing blank

    s57 = _on_canvas_text(str(draft), 57)
    assert "고백의 찬양" in s57 and "[ 테스트 고백 ]" in s57  # heading kept, bracketed title set
    assert "테스트 고백" in _on_canvas_text(str(draft), 59)  # lower-third title banner
    s60 = _on_canvas_text(str(draft), 60)
    assert "첫째 줄" in s60 and "둘째 줄" in s60
    assert "셋째 줄" in _on_canvas_text(str(draft), 61)
    # the trailing blank right after the resized lyric block holds no leftover lyrics
    assert "줄" not in _on_canvas_text(str(draft), 62)


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
    without reopening the deck. Reads the open `front document` (#117), not the on-disk file."""
    script = (
        "on run argv\n"
        'tell application "Keynote"\n'
        "  set d to front document\n"
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


def _slide_count(key_path: str) -> int:
    """Read the open draft's total slide count (Mac-only; reads `front document`, #117)."""
    out = subprocess.run(
        [
            "osascript",
            "-e",
            'on run argv\ntell application "Keynote"\n'
            "set d to front document\nset n to count of slides of d\n"
            "return n as text\nend tell\nend run\n",
            key_path,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    ).stdout
    return int(out.strip())


def _image_count(key_path: str, slide_index: int) -> int:
    """Number of images on a 1-based slide (Mac-only; reads the open `front document`, #117)."""
    out = subprocess.run(
        [
            "osascript",
            "-e",
            'on run argv\ntell application "Keynote"\n'
            "set d to front document\n"
            "set n to count of images of slide ((item 2 of argv) as integer) of d\n"
            "return n as text\nend tell\nend run\n",
            key_path,
            str(slide_index),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    ).stdout
    return int(out.strip())


@pytest.mark.local_only
def test_fill_hymn_slides_live_replaces_block_and_keeps_titles(
    real_template_key: Path, tmp_path: Path
) -> None:
    """Replacing last week's hymn pages with fewer PNGs must trim the leftovers (total drops by the
    surplus), place an aspect-fill image covering each new page, and leave the section's title/intro
    text slides (before the detected image block) image-free — no hymn page bleeds onto them."""
    from PIL import Image

    draft = tmp_path / "draft.key"
    save_draft(str(real_template_key), str(draft))
    before = _slide_count(str(draft))

    first, last = hymn_image_block(str(draft), 97)
    existing = last - first + 1
    assert first >= 97 and existing >= 2  # template carries last week's multi-page hymn

    images = []
    for i in range(1, 3):  # fewer than `existing` to force a trim of leftovers
        png = tmp_path / f"slide-{i}.png"
        Image.new("RGB", (400, 300), "white").save(png)
        images.append(str(png))

    n = fill_hymn_slides(str(draft), 97, images)
    assert n == 2
    assert _slide_count(str(draft)) == before - (existing - 2)  # leftover pages trimmed
    assert _image_count(str(draft), first - 1) == 0  # title/intro slide before the block untouched

    for idx in (first, first + 1):
        cnt, _px, _py, w, h, dw, dh = _last_image_frame(str(draft), idx)
        assert cnt == 1  # last week's page was cleared, not stacked under the new one
        assert w >= dw - 1 and h >= dh - 1  # the placed image covers the slide


# ---------------------------------------------------------------------------
# build — section orchestration (CI-safe: fill primitives stubbed, no Mac)
# ---------------------------------------------------------------------------


def _stub_fills(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    """Replace every fill primitive build() drives with a recorder; return the call log.

    build() calls these by their module-global name, so patching them on `B` intercepts the
    dispatch without touching osascript — the test asserts the order/anchors/args headlessly.
    """
    calls: list[tuple] = []

    def rec(name):
        def f(*args, **kwargs):
            calls.append((name, args, kwargs))
            return 0
        return f

    for name in (
        "save_draft",
        "set_date_slides",
        "delete_slides",
        "set_sermon_title_slide",
        "set_sermon_ref_slide",
        "fill_verse_slides",
        "fill_announcement_slides",
        "set_offering_hymn_title_slide",
        "fill_hymn_slides",
        "fill_choir_slides",
        "fill_confession_slides",
        "set_call_to_worship_ref",
        "fill_worship_songs",
        "finalize_draft",
    ):
        monkeypatch.setattr(B, name, rec(name))
    # Stubbed silently (not recorded): build() calls it before save_draft to clear stale docs;
    # it would otherwise launch Keynote and isn't part of the section-dispatch sequence.
    monkeypatch.setattr(B, "_ensure_keynote_ready", lambda *a, **k: None)
    return calls


def _full_run() -> ServiceData:
    """A reviewed run with every section's content in its top-level field (build ignores the
    worship_order skeleton)."""
    return ServiceData(
        date="2026년 6월 7일",
        worship_songs=[{"title": "주 은혜임을", "lines": ["한 줄", "두 줄"], "composer": "작곡"}],
        choir_song={"title": "사랑은", "lines": ["사랑은", "오래참고"], "composer": "(윤학준 곡)"},
        confession_song={"title": "주만 바라볼찌라", "lines": ["하나님의 사랑을"], "composer": ""},
        call_to_worship_passage=[{"number": 1, "korean": "보라 형제가", "english": "Behold"}],
        call_to_worship_ref="시 133:1-3",
        sermon_passage=[{"number": 1, "korean": "구름 같이", "english": "cloud"}],
        sermon_title="믿음의 경주",
        sermon_ref="히 12:1-2",
        announcements=["공지 하나", "공지 둘"],
        offering_hymn_number="455",
        offering_hymn_title="주님의 마음을 본받는 자",
        offering_hymn_images=["slide-1.png", "slide-2.png"],
    )


def test_build_dispatches_sections_back_to_front(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _stub_fills(monkeypatch)

    assert build(_full_run(), "tpl.key", "out.key") == "out.key"

    names = [c[0] for c in calls]
    # save_draft first, then date (count-neutral), then the ad-hoc 말씀 special-block delete
    # (highest-index count-changing op, so the 135 anchor is still exact here); then back-to-front
    # by anchor: title @134 (before the 129 verse fill shifts it) → sermon verses → announce →
    # hymn → choir → ctw → medley.
    assert names == [
        "save_draft",
        "set_date_slides",
        "delete_slides",           # 말씀 ad-hoc special block @135 (#97)
        "set_sermon_title_slide",  # 말씀 title @134
        "fill_verse_slides",       # 말씀 @129
        "set_sermon_ref_slide",    # 말씀 ref recap @127 (count-neutral, #107)
        "fill_announcement_slides",  # 교회소식 @117
        "set_offering_hymn_title_slide",  # 봉헌 title @97 (count-neutral)
        "fill_hymn_slides",        # 봉헌 images @97
        "fill_choir_slides",       # 성가대 @77
        "fill_confession_slides",  # 고백의 찬양 @57 (#109)
        "set_call_to_worship_ref",  # 예배의 부름 ref slide @47 (count-neutral, #107)
        "fill_verse_slides",       # 예배의 부름 @48
        "fill_worship_songs",      # 찬양 medley @6
        "finalize_draft",          # single save of the open front document (#117)
    ]

    by_name = {c[0]: c for c in calls}
    assert by_name["save_draft"][1] == ("tpl.key", "out.key")
    # the ad-hoc 말씀 special block: 18 slides dropped at the template anchor 135 (#97).
    assert by_name["delete_slides"][1] == ("out.key", 135, 18)
    # date slide takes the top-level sermon title + bracketed ref.
    assert by_name["set_date_slides"][1] == ("out.key", "2026년 6월 7일", "믿음의 경주", "[히 12:1-2]")
    # standalone 말씀 title slide (134) gets the same sermon title + bracketed ref.
    assert by_name["set_sermon_title_slide"][1] == ("out.key", 134, "믿음의 경주", "[히 12:1-2]")

    sermon_call, ctw_call = (c for c in calls if c[0] == "fill_verse_slides")
    assert sermon_call[1][0:2] == ("out.key", 129)
    assert sermon_call[2] == {"existing_count": 4}
    assert sermon_call[1][4] == [Verse(1, "구름 같이", "cloud")]  # passage dict → Verse
    assert ctw_call[1][0:2] == ("out.key", 48)
    assert ctw_call[2] == {"existing_count": 1}
    assert ctw_call[1][4] == [Verse(1, "보라 형제가", "Behold")]

    # 예배의 부름 ref-display slide (47) gets this week's bare reference (#107).
    assert by_name["set_call_to_worship_ref"][1] == ("out.key", 47, "시 133:1-3")
    # 말씀 scripture-ref recap slide (127) gets this week's sermon reference (#107).
    assert by_name["set_sermon_ref_slide"][1] == ("out.key", 127, "히 12:1-2")

    announce = by_name["fill_announcement_slides"]
    assert announce[1] == ("out.key", 117, ["공지 하나", "공지 둘"])
    assert announce[2] == {"existing_count": 5}

    hymn_title = by_name["set_offering_hymn_title_slide"]
    assert hymn_title[1] == ("out.key", 97, "455", "주님의 마음을 본받는 자")  # number + title

    hymn = by_name["fill_hymn_slides"]
    assert hymn[1] == ("out.key", 97, ["slide-1.png", "slide-2.png"])  # detects the block itself
    assert hymn[2] == {}

    choir = by_name["fill_choir_slides"]
    assert choir[1] == (
        "out.key",
        77,
        Song(title="사랑은", lines=["사랑은", "오래참고"], composer="(윤학준 곡)"),
    )

    confession = by_name["fill_confession_slides"]
    assert confession[1] == (
        "out.key",
        57,
        Song(title="주만 바라볼찌라", lines=["하나님의 사랑을"], composer=""),
    )

    medley = by_name["fill_worship_songs"]
    assert medley[1] == ("out.key", 6, 41, [Song(title="주 은혜임을", lines=["한 줄", "두 줄"], composer="작곡")])


def test_build_skips_empty_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _stub_fills(monkeypatch)

    build(ServiceData(date="2026년 6월 7일"), "tpl.key", "out.key")

    # No worship_order, no announcements → only the copy, the count-neutral date stamp, the
    # unconditional ad-hoc special-block delete (always present in the template), and the final
    # single save (#117) run.
    assert [c[0] for c in calls] == [
        "save_draft",
        "set_date_slides",
        "delete_slides",
        "finalize_draft",
    ]
    assert calls[1][1] == ("out.key", "2026년 6월 7일", "", "")
    assert calls[2][1] == ("out.key", 135, 18)
