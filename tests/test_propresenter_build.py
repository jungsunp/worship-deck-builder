"""Unit tests for the ``.pro`` serialization library (#172) — pure protobuf, CI-safe."""

import shutil
import subprocess
from pathlib import Path

import pytest

from worship_deck.propresenter import pb  # noqa: F401 -- puts pb/ on sys.path

# Bindings are generated (scripts/gen_proto.sh), not committed — skip if absent.
presentation_pb2 = pytest.importorskip(
    "presentation_pb2", reason="run scripts/gen_proto.sh to generate protobuf bindings"
)
import graphicsData_pb2  # deliberately after the importorskip guard

from worship_deck.propresenter import build, elements, rtf, styles

_KO = "주 하나님"


def _rtf_text(slide) -> str:
    return b"".join(
        e.element.text.rtf_data for e in slide.elements if e.element.HasField("text")
    ).decode()


# ── RTF ───────────────────────────────────────────────────────────────────────

def test_escape_passes_ascii_and_escapes_rtf_syntax():
    assert rtf.escape("Psalm 133:1") == "Psalm 133:1"
    assert rtf.escape("a\\b{c}") == "a\\\\b\\{c\\}"


def test_escape_breaks_lines_with_backslash_lf():
    """In-slide line breaks are backslash + LF — not \\par, which would start a paragraph."""
    assert rtf.escape("one\ntwo") == "one\\\ntwo"


def test_escape_wraps_hangul_into_signed_16_bit():
    """RTF \\u takes a signed 16-bit value, so Hangul (>32767) must come out negative."""
    assert rtf.escape("한") == f"\\u{0xD55C - 65536} "
    assert rtf.escape("•") == "\\u8226 "  # below the wrap point, stays positive


def test_document_doubles_point_size_and_indexes_colors_from_one():
    gold = styles.Style(styles.FONT_BOLD, 26, styles.ACCENT, bold=True)
    body = styles.Style(styles.FONT_REGULAR, 47, styles.INK)
    text = rtf.document([("9 ", gold), ("빛이 있었나니", body)]).decode()

    assert "\\fs52 " in text and "\\fs94 " in text  # points × 2
    assert "{\\colortbl;\\red255\\green212\\blue71;\\red255\\green255\\blue255;}" in text
    assert "\\cf1 " in text and "\\cf2 " in text  # index 0 is RTF's reserved blank slot
    assert text.count("\\fnil\\fcharset0") == 2  # one font-table entry per distinct face


def test_document_reuses_one_table_entry_per_repeated_style():
    style = styles.LYRIC_KO
    text = rtf.document([("a", style), ("b", style)]).decode()
    assert text.count("\\fnil\\fcharset0") == 1
    assert text.count("\\red") == 1


def test_document_line_spacing_is_twips():
    style = styles.Style(styles.FONT_REGULAR, 46, line_spacing=15.0)
    assert "\\slleading300\\pardirnatural" in rtf.plain("x", style).decode()


@pytest.mark.local_only
def test_macos_rtf_parser_reads_the_korean_back(tmp_path):
    """ProPresenter renders ``rtf_data`` with Cocoa's RTF parser, so round-trip our escaping
    through the same parser (``textutil``) — the cheap proxy for opening the deck by hand."""
    if not shutil.which("textutil"):
        pytest.skip("textutil is macOS-only")

    lines = ["다시 한 번 외쳐 부르니", "예수여 나를 돌아 보소서"]
    rtf_file = tmp_path / "lyric.rtf"
    rtf_file.write_bytes(rtf.plain("\n".join(lines), styles.LYRIC_KO))
    out = subprocess.run(
        ["textutil", "-convert", "txt", "-stdout", str(rtf_file)],
        capture_output=True, text=True, check=True,
    )

    assert out.stdout.splitlines() == lines


# ── Elements ──────────────────────────────────────────────────────────────────

def test_text_element_is_flagged_and_mirrors_its_style():
    slide = styles.liturgy("사도신경", ["전능하사 천지를 만드신"])
    text_elements = [e for e in slide.elements if e.element.HasField("text")]

    assert all(e.info == 3 for e in text_elements)  # IS_TEMPLATE_ELEMENT | IS_TEXT_ELEMENT
    body = text_elements[0].element.text  # elements[0] is the topmost layer — the body copy
    assert body.attributes.font.name == styles.LITURGY_BODY.font
    assert body.attributes.font.size == styles.LITURGY_BODY.size
    assert body.vertical_alignment == graphicsData_pb2.Graphics.Text.VERTICAL_ALIGNMENT_TOP


def test_every_element_carries_the_unit_square_path():
    """ProPresenter writes a closed unit-square rect path on every element; omitting it
    leaves the element unrenderable."""
    slide = styles.section_divider("봉 헌", "(찬 283장)")
    for wrapper in slide.elements:
        path = wrapper.element.path
        assert path.closed
        assert [(p.point.x, p.point.y) for p in path.points] == [(0, 0), (1, 0), (1, 1), (0, 1)]


def test_lyric_slide_uses_per_line_strips():
    slide = styles.worship_lyric_ko(["다시 한 번 외쳐 부르니", "예수여 나를 돌아 보소서"])
    element = slide.elements[0].element

    assert element.fill.enable  # the gate — a fill without it never draws
    assert element.fill.color.alpha == 1.0
    assert element.text_line_mask.enabled
    assert (
        element.text_line_mask.mask_style
        == graphicsData_pb2.Graphics.Text.LineFillMask.LINE_MASK_STYLE_LINE_WIDTH
    )


def test_fullscreen_slide_is_tinted_and_framed_without_a_background_effect():
    slide = styles.verse_fullscreen("[요 1:9, 개역한글]", [(9, "참 빛 곧")], "[John 1:9, ESV]", [(9, "The true light")])
    shapes = [e.element for e in slide.elements if not e.element.HasField("text")]

    assert slide.draws_background_color
    # backgroundEffect crashes ProPresenter 21.4 on selection — the blur is #224's job.
    assert not any(s.fill.HasField("backgroundEffect") for s in shapes)
    frame = shapes[1]
    assert frame.path.shape.type == graphicsData_pb2.Graphics.Path.Shape.TYPE_ROUNDED_RECTANGLE
    assert frame.stroke.enable and frame.stroke.width == styles.FRAME_STROKE_WIDTH


def test_image_element_sets_the_media_url_and_enables_the_fill(tmp_path):
    png = tmp_path / "hymn 283.png"
    png.write_bytes(b"")
    slide = styles.image(str(png))
    media = slide.elements[0].element.fill.media

    assert slide.elements[0].element.fill.enable
    assert media.url.absolute_string.startswith("file:///")
    assert media.url.absolute_string.endswith("hymn%20283.png")  # path is percent-encoded
    assert media.HasField("image")


def test_web_element_carries_the_url_as_web_content():
    slide = styles.blank_green()
    elements.web(slide, (0.0, 0.0, 640.0, 200.0), "https://glossa.live/")
    media = slide.elements[0].element.fill.media

    assert media.HasField("web_content")
    assert media.web_content.url.absolute_string == "https://glossa.live/"


# ── Presentation / cue / group wiring ─────────────────────────────────────────

def test_new_presentation_identifies_itself_as_propresenter():
    pres = build.new_presentation("2026-08-16")
    assert pres.name == "2026-08-16"
    assert pres.uuid.string == pres.uuid.string.upper()
    assert pres.application_info.application_version.major_version == build.PP_VERSION[0]


def test_new_slide_dispatches_on_style_key_and_rejects_unknown_ones():
    assert set(styles.BUILDERS) == set(styles.STYLE_KEYS)
    slide = build.new_slide("liturgy", "주기도문", ["하늘에 계신 우리 아버지여"])
    assert slide.size.width == styles.CANVAS[0]
    with pytest.raises(KeyError):
        build.new_slide("no_such_style")


def test_cue_action_is_typed_as_a_presentation_slide():
    """The oneof alone isn't enough — ProPresenter routes on Action.type."""
    pres = build.new_presentation("demo")
    build.add_cue(pres, styles.blank_green(), "blank")
    action = pres.cues[0].actions[0]

    assert action.type == action.ACTION_TYPE_PRESENTATION_SLIDE
    assert action.slide.presentation.base_slide.size.height == styles.CANVAS[1]


def test_group_references_its_cues_by_uuid():
    pres = build.new_presentation("demo")
    uuids = [build.add_cue(pres, styles.blank_green(), f"s{i}") for i in range(3)]
    build.add_group(pres, "찬양", styles.GROUP_COLORS["찬양"], uuids)
    group = pres.cue_groups[0]

    assert group.group.name == "찬양"
    assert [u.string for u in group.cue_identifiers] == [c.uuid.string for c in pres.cues]


def test_arrangement_references_groups_and_becomes_the_selected_one():
    pres = build.new_presentation("demo")
    cue = build.add_cue(pres, styles.blank_green(), "s")
    verse = build.add_group(pres, "V1", None, [cue])
    chorus = build.add_group(pres, "C", None, [cue])
    arrangement = build.add_arrangement(pres, "Full", [verse, chorus, verse])

    assert [u.string for u in pres.arrangements[0].group_identifiers] == [
        verse.string, chorus.string, verse.string
    ]
    assert pres.selected_arrangement.string == arrangement.string


def test_no_slide_carries_a_transition():
    """ProPresenter 21.4 drops any slide that carries a transition without a real Effect, so
    the generator must not write one at all (see the note in build.py; #174 owns this)."""
    pres = build.new_presentation("demo")
    build.add_cue(pres, build.new_slide("liturgy", "사도신경", ["전능하사"]), "s")

    assert not pres.HasField("transition")
    assert not pres.cues[0].actions[0].slide.presentation.HasField("transition")


# ── Save / load ───────────────────────────────────────────────────────────────

def test_serialize_and_load_round_trip_keeps_korean_text(tmp_path):
    pres = build.new_presentation("2026-08-16")
    slide = build.new_slide("worship_lyric_ko", [_KO, "지으신 모든 세계"])
    build.add_group(pres, "찬양", styles.GROUP_COLORS["찬양"], [build.add_cue(pres, slide, "C1")])

    out = build.serialize(pres, str(tmp_path / "week.pro"))
    again = build.load(out)

    assert again.name == "2026-08-16"
    assert len(again.cues) == 1
    reloaded = again.cues[0].actions[0].slide.presentation.base_slide
    assert _rtf_text(reloaded) == _rtf_text(slide)
    assert rtf.escape(_KO) in _rtf_text(reloaded)
    # Re-serializing byte-for-byte proves nothing landed in unknown fields on the way back.
    assert again.SerializeToString() == Path(out).read_bytes()
