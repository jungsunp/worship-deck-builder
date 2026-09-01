"""Unit tests for the ``.pro`` serialization library (#172) — pure protobuf, CI-safe."""

import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from worship_deck.propresenter import pb  # noqa: F401 -- puts pb/ on sys.path

# Bindings are generated (scripts/gen_proto.sh), not committed — skip if absent.
presentation_pb2 = pytest.importorskip(
    "presentation_pb2", reason="run scripts/gen_proto.sh to generate protobuf bindings"
)
import graphicsData_pb2  # deliberately after the importorskip guard

from worship_deck.bible import layout
from worship_deck.bible.verses import Verse
from worship_deck.lyrics import linebreak
from worship_deck.parse import ServiceData
from worship_deck.propresenter import build, content, elements, rtf, styles

_KO = "주 하나님"


def _rgb(color) -> tuple[int, int, int]:
    return tuple(round(c * 255) for c in (color.red, color.green, color.blue))


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


def _has_frame(slide) -> bool:
    """Whether the slide draws the 네이비 프레임 outline (the tint alone does not count)."""
    return any(
        e.element.path.shape.type == graphicsData_pb2.Graphics.Path.Shape.TYPE_ROUNDED_RECTANGLE
        for e in slide.elements
    )


def test_the_opening_and_closing_plates_drop_the_frame_outline():
    """The operator took the outline off the plates and the fixed-wording cards restyling a draft
    — "removed borderline to make it cleaner" (#178 review). It stays wherever content runs to the
    edges, which is every slide that is not a plate."""
    assert not _has_frame(styles.service_intro("1부", "제목", "삼상 14:1-23", "2026년 8월 30일"))
    assert not _has_frame(styles.service_outro("1부", "2026년 8월 30일"))
    assert not _has_frame(styles.text_card(["노스필드 장로교회는"]))

    assert _has_frame(styles.section_divider("봉 헌"))
    assert _has_frame(styles.liturgy("사도신경", ["나는"]))
    assert _has_frame(styles.announcement("교회 소식", ["1. 안내"]))


def test_the_korean_scripture_body_is_set_regular_not_bold():
    """84pt bold 개역한글 filling five lines reads as a wall on the navy ground; the operator set it
    back to Regular restyling a draft (#178 review). The gold verse numbers stay bold."""
    assert not styles.VERSE_KO.bold
    assert styles.VERSE_KO.font == styles.FONT_REGULAR
    assert styles.VERSE_NUMBER.bold


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


# ── Sung-lyric slides + fillers (#175) ────────────────────────────────────────

def _slide_of(pres, index):
    return pres.cues[index].actions[0].slide.presentation.base_slide


def _line_count(pres, index) -> int:
    """How many text lines a cue's slide carries — an in-slide break is backslash + LF."""
    return _rtf_text(_slide_of(pres, index)).count("\\\n") + 1


def _green(slide) -> bool:
    r, g, b = (round(c * 255) for c in (
        slide.background_color.red, slide.background_color.green, slide.background_color.blue))
    return slide.draws_background_color and (r, g, b) == styles.CHROMA_GREEN


def test_sung_lyric_slides_are_backed_with_the_church_key_green():
    """Left transparent they render black over the camera instead of keying out (#192)."""
    assert styles.CHROMA_GREEN == (0x81, 0xD6, 0x54)
    assert _green(styles.worship_lyric_ko([_KO]))
    assert _green(styles.song_banner("다시 한 번"))
    assert _green(styles.blank_green())
    # Full-screen sections deliberately stay opaque — they replace the camera, not overlay it.
    assert not _green(styles.section_divider("봉 헌"))


def test_song_banner_puts_the_title_on_one_strip_in_the_lyric_zone():
    slide = styles.song_banner("다시 한 번")
    element = slide.elements[0].element

    assert element.text_line_mask.enabled  # same Option A strip idiom as the lyrics
    assert element.bounds.origin.y + element.bounds.size.height == (
        styles.CANVAS[1] - styles.LYRIC_ZONE_BOTTOM
    )


def test_fill_song_emits_banner_then_lyrics_then_a_trailing_blank():
    pres = build.new_presentation("demo")
    build.fill_song(pres, {"title": "다시 한 번", "lines": ["가", "나", "다"]})

    # 3 lines -> 2 slides (2 + 1), between the title banner and the blank.
    assert len(pres.cues) == 4
    assert _line_count(pres, 1) == 2 and _line_count(pres, 2) == 1
    assert rtf.escape("가\n나") in _rtf_text(_slide_of(pres, 1))
    assert rtf.escape("다") in _rtf_text(_slide_of(pres, 2))
    assert not _slide_of(pres, 3).elements  # the blank green cue
    group = pres.cue_groups[0]
    assert group.group.name == "다시 한 번"
    assert len(group.cue_identifiers) == 4


def test_fill_song_breaks_a_stanza_and_survives_empty_lyrics():
    pres = build.new_presentation("demo")
    build.fill_song(pres, {"title": "A", "lines": ["가", "", "나"]})
    assert len(pres.cues) == 4  # blank line forces a slide break: 가 | 나

    empty = build.new_presentation("demo")
    build.fill_song(empty, {"title": "B", "lines": []})
    assert len(empty.cues) == 2  # banner + blank only


def test_fill_song_rebreaks_overlong_lines_that_never_saw_assemble():
    """Choir pastes / typed lyrics skip linebreak.rebreak at assemble; an unbroken line would
    wrap inside a strip box measured for fewer lines, clipping the last one."""
    long_line = "주의 사랑이 내 안에 넘쳐 흐르네 언제나 나와 함께 하시네"
    assert len(long_line) > linebreak.MAX_CHARS
    pres = build.new_presentation("demo")
    build.fill_song(pres, {"title": "A", "lines": [long_line]})

    assert len(pres.cues) == 3  # banner + one lyric slide + blank
    assert _line_count(pres, 1) == 2  # the one long line, re-broken and packed onto one slide


def test_fill_song_labels_lyric_cues_and_plays_the_arrangement():
    """Labeled sections (#113) play in arrangement order with the label as the cue name; they
    stay in one group until #176 gives each label its own group + Arrangement."""
    pres = build.new_presentation("demo")
    build.fill_song(pres, {
        "title": "A",
        "lines": ["v1", "", "c1"],
        "sections": [{"label": "V1", "lines": ["v1"]}, {"label": "C", "lines": ["c1"]}],
        "arrangement": "V1 C V1",
    })

    assert [c.name for c in pres.cues] == ["A", "V1", "C", "V1", ""]
    assert len(pres.cue_groups) == 1
    assert not pres.arrangements


def test_lyric_cues_carry_a_colored_slide_label_without_becoming_groups():
    """ProPresenter's per-slide label (Action.Label) is a different field from Cue.name — the one
    PP actually shows in the grid — so V1/C/B stay readable with one group per song (Decision 4)."""
    pres = build.new_presentation("demo")
    build.fill_song(pres, {
        "title": "A",
        "lines": ["v1", "", "c1"],
        "sections": [{"label": "V1", "lines": ["v1"]}, {"label": "C", "lines": ["c1"]}],
        "arrangement": "V1 C V1",
    })

    labels = [c.actions[0].label.text for c in pres.cues]
    assert labels == ["", "V1", "C", "V1", ""]  # banner and trailing blank stay unlabeled
    v1, c = pres.cues[1].actions[0].label, pres.cues[2].actions[0].label
    assert _rgb(v1.color) == styles.section_color("V1") != _rgb(c.color)
    assert len(pres.cue_groups) == 1


def test_medley_songs_get_distinct_group_colors():
    pres = build.new_presentation("demo")
    build.fill_worship_songs(pres, [{"title": t, "lines": ["가"]} for t in "ABC"])

    colors = [_rgb(g.group.color) for g in pres.cue_groups]
    assert colors == list(styles.SONG_COLORS[:3])  # one hue per song, so songs read apart


def test_fill_worship_songs_gives_each_medley_song_its_own_group():
    pres = build.new_presentation("demo")
    build.fill_worship_songs(pres, [
        {"title": "첫째", "lines": ["가"]},
        {"title": "둘째", "lines": ["나"]},
    ])

    assert [g.group.name for g in pres.cue_groups] == ["첫째", "둘째"]
    assert len(pres.cues) == 6  # (banner + lyric + blank) x 2


def test_fill_confession_is_one_group_headed_by_its_divider():
    """고백의 찬양 and the song it announces are a single section to the operator, so they share
    one group bar — the medley is the only place a song opens a bar of its own (#178 review)."""
    pres = build.new_presentation("demo")
    build.fill_confession(pres, {"title": "예수 나의 첫사랑", "lines": ["가"]})

    assert [g.group.name for g in pres.cue_groups] == ["고백의 찬양"]
    assert len(pres.cue_groups[0].cue_identifiers) == 5  # divider + blank + banner + lyric + blank
    divider = _rtf_text(_slide_of(pres, 0))
    assert rtf.escape("고백의 찬양") in divider
    assert rtf.escape("예수 나의 첫사랑") in divider
    assert "[" not in divider


# ── Section fills + the whole-deck walk (#178) ────────────────────────────────

def _verse(number: int, korean: str, english: str) -> dict:
    return {"number": number, "korean": korean, "english": english}


def _service_data(**overrides) -> ServiceData:
    """A week's reviewed data, trimmed to what the .pro builder reads."""
    data = ServiceData(
        date="2026년 8월 23일",
        sermon_title="이를 행하여 나를 기념하라",
        sermon_ref="눅 22:14-24",
        sermon_passage=[_verse(14, "때가 이르매 예수께서 사도들과 함께 앉으사", "And when the hour came")],
        call_to_worship_ref="시 133:1-3",
        call_to_worship_passage=[_verse(1, "형제가 연합하여 동거함이", "Behold, how good")],
        announcements=["1. 성찬식\n\n7/5 (오늘) 성찬식이 있습니다."],
        worship_songs=[{"title": "다시 한 번", "lines": ["다시 한 번 외쳐 부르니"]}],
        confession_song={"title": "주만 바라볼찌라", "lines": ["믿음으로 가네"]},
        choir_song={"title": "사랑은", "composer": "(윤학준 곡)", "lines": ["내가 사람의 방언과"]},
        offering_hymn_number="70",
        offering_hymn_title="피난처 있으니",
    )
    for field, value in overrides.items():
        setattr(data, field, value)
    return data


def _group_names(pres) -> list[str]:
    return [g.group.name for g in pres.cue_groups]


def _cues_of(pres, group_name: str) -> list:
    """The cues a named group owns, in play order."""
    by_uuid = {c.uuid.string: c for c in pres.cues}
    group = next(g for g in pres.cue_groups if g.group.name == group_name)
    return [by_uuid[u.string] for u in group.cue_identifiers]


def _slide_of_cue(cue):
    return cue.actions[0].slide.presentation.base_slide


def test_build_walks_the_whole_service_in_liturgy_order(tmp_path):
    """The regression guard for a ground-up deck: under Keynote half these sections rode along
    inside master.key untouched, so a missing one was impossible. Here every one is generated,
    and a section silently dropping out would show up only on a Sunday morning."""
    pres = build.load(build.build(_service_data(), str(tmp_path / "week.pro"))[0])

    assert _group_names(pres) == [
        "예배 시작", "다시 한 번", "예배의 부름", "회개로의 초대", "죄사함의 선포",
        "고백의 찬양", "사도신경", "성가대 찬양", "봉 헌",
        "환영 및 인사", "교회 소식", "합심 기도", "말씀", "파송의 노래", "축복의 통로",
        "축도", "주기도문", "예배 마침",
    ]


def test_build_reports_per_section_timings(tmp_path):
    _, steps = build.build(_service_data(), str(tmp_path / "week.pro"))

    assert steps["serialize"] >= 0
    assert {"opening", "sermon", "lords_prayer", "ending"} <= set(steps)


def test_empty_service_data_still_builds_every_fixed_wording_section(tmp_path):
    """Nothing rides along for free in a generated deck: with no bulletin content at all the
    liturgy, the dividers and the bookend cards must still be there."""
    pres = build.load(build.build(ServiceData(), str(tmp_path / "empty.pro"))[0])

    assert _group_names(pres) == [
        "예배 시작", "회개로의 초대", "죄사함의 선포", "사도신경", "봉 헌",
        "환영 및 인사", "합심 기도", "파송의 노래", "축복의 통로", "축도", "주기도문", "예배 마침",
    ]


def test_sermon_ends_on_a_green_blank_for_the_glossa_prop(tmp_path):
    """The ATEM keys ProPresenter's output and a cleared output is black, which keys nothing and
    covers the camera. The operator parks the sermon on a real green cue so the Glossa prop
    (#177) composites over the live shot."""
    pres = build.load(build.build(_service_data(), str(tmp_path / "week.pro"))[0])
    cues = _cues_of(pres, "말씀")

    assert _green(_slide_of_cue(cues[-1]))
    assert not _slide_of_cue(cues[-1]).elements
    # ...and the verse plates before it stay opaque navy — they replace the camera.
    assert not any(_green(_slide_of_cue(c)) for c in cues[:-1])


def test_verse_slides_pack_a_long_passage_across_cues():
    """Same density model as Keynote (#115), fed this deck's baked box sizes instead of measured
    ones — a short passage stays on one plate, a long one spills."""
    short = [_verse(1, "형제가 연합하여 동거함이 어찌 그리 선하고 아름다운고", "Behold, how good and pleasant it is")]
    long = [
        _verse(n, "때가 이르매 예수께서 사도들과 함께 앉으사 이르시되 내가 고난을 받기 전에 너희와 함께 이 유월절 먹기를 원하고 원하였노라",
               "And when the hour came, he reclined at table, and the apostles with him.")
        for n in range(14, 25)
    ]

    one = build.new_presentation("x")
    build.fill_verse_slides(one, "예배의 부름", "시 133:1-3", [Verse(**v) for v in short])
    many = build.new_presentation("x")
    build.fill_verse_slides(many, "말씀", "눅 22:14-24", [Verse(**v) for v in long])

    assert len(one.cues) == 2  # divider + one plate
    assert len(many.cues) > 2 + 1


def test_verse_plate_carries_both_translations_and_the_citation_labels():
    pres = build.new_presentation("x")
    build.fill_verse_slides(
        pres, "예배의 부름", "시 133:1-3",
        [Verse(**_verse(1, "형제가 연합하여 동거함이", "Behold, how good"))],
    )
    text = _rtf_text(_slide_of(pres, 1))

    assert rtf.escape("[시 133:1-3, 개역한글]") in text
    assert "[Psalms 133:1-3, ESV]" in text
    assert rtf.escape("형제가 연합하여 동거함이") in text
    assert "Behold, how good" in text


def test_apostles_creed_emits_both_forms_the_deck_carries(tmp_path):
    """The template holds a responsive call-and-response (master 70-72) AND the traditional
    recitation (74-75); the operator uses whichever the service calls for, so both ship."""
    pres = build.load(build.build(ServiceData(), str(tmp_path / "empty.pro"))[0])
    cues = _cues_of(pres, "사도신경")

    assert len(cues) == 1 + 3 + 2  # divider + responsive + traditional
    assert rtf.escape("여러분은 하나님을 믿으십니까?") in _rtf_text(_slide_of_cue(cues[1]))
    assert rtf.escape("전능하사 천지를 만드신") in _rtf_text(_slide_of_cue(cues[4]))


def test_liturgy_wording_is_sourced_not_invented():
    """These were dumped from the church's own master.key — several Korean translations of each
    are in circulation and the congregation recites one of them from memory."""
    assert len(content.APOSTLES_CREED_RESPONSIVE) == 3
    assert len(content.APOSTLES_CREED) == 2
    assert content.LORDS_PRAYER[0][0] == "하늘에 계신 우리 아버지여"
    assert content.LORDS_PRAYER[-1][-1] == "아멘"


def test_choir_divider_carries_the_booth_lighting_cue_as_a_slide_note(tmp_path):
    """Master slide 76 is a presenter note, not congregation-facing — it belongs in
    ProPresenter's notes pane, not on the canvas."""
    pres = build.load(build.build(_service_data(), str(tmp_path / "week.pro"))[0])
    divider = _cues_of(pres, "성가대 찬양")[0]
    notes = divider.actions[0].slide.presentation.notes

    assert rtf.escape(content.CHOIR_LIGHT_NOTE) in notes.rtf_data.decode()
    assert rtf.escape(content.CHOIR_LIGHT_NOTE) not in _rtf_text(_slide_of_cue(divider))


def test_opening_plates_carry_the_week_and_the_closing_plates_the_date(tmp_path):
    pres = build.load(build.build(_service_data(), str(tmp_path / "week.pro"))[0])
    opening = [_rtf_text(_slide_of_cue(c)) for c in _cues_of(pres, "예배 시작")]
    ending = [_rtf_text(_slide_of_cue(c)) for c in _cues_of(pres, "예배 마침")]

    assert rtf.escape("1부 예배를 시작합니다.") in opening[0]
    assert rtf.escape("2부 예배를 시작합니다.") in opening[1]
    assert all(rtf.escape("2026년 8월 23일") in t for t in opening[:2])
    assert rtf.escape("이를 행하여 나를 기념하라") in opening[0]
    assert rtf.escape("1부 예배를 마칩니다.") in ending[0]
    assert rtf.escape(content.MOTTO[0]) in opening[2]


def test_divider_subtitles_carry_no_brackets(tmp_path):
    """master.key writes the week's song title as ``[ 믿음으로 우리는 ]``; the operator dropped the
    brackets across the divider slides (#178 review). The scripture slides' own reference labels
    keep theirs — those sit inside the body, where they do need setting apart."""
    pres = build.load(build.build(_service_data(), str(tmp_path / "week.pro"))[0])
    dividers = [_cues_of(pres, name)[0] for name in ("예배의 부름", "고백의 찬양", "성가대 찬양")]

    for cue in dividers:
        assert "[" not in _rtf_text(_slide_of_cue(cue))


def test_keyed_label_keys_over_the_camera_on_the_measured_plate():
    """#234: these headings annotate the live shot, so the slide is green-backed (an unbacked one
    renders black and covers the camera, #192) and carries the plate PNG instead of a navy frame."""
    for placement in ("top", "bottom"):
        slide = styles.keyed_label("회개로의 초대", placement)
        assert _green(slide)
        assert not _has_frame(slide)
        assert "m1-angled-bar" in _images_of(slide)

        rect, _ = styles.KEYED_LABEL_PLACEMENTS[placement]
        art = next(e.element.bounds for e in slide.elements
                   if e.element.fill.HasField("media"))
        assert (art.origin.x, art.origin.y) == (rect[0], rect[1])
        assert (art.size.width, art.size.height) == (rect[2], rect[3])


def test_keyed_label_text_stays_inside_the_plate():
    for placement in ("top", "bottom"):
        slide = styles.keyed_label("죄사함의 선포", placement)
        rect, _ = styles.KEYED_LABEL_PLACEMENTS[placement]
        text = next(e.element.bounds for e in slide.elements if e.element.HasField("text"))
        assert text.origin.x >= rect[0]
        assert text.origin.x + text.size.width <= rect[0] + rect[2]
        assert text.origin.y >= rect[1]
        assert text.origin.y + text.size.height <= rect[1] + rect[3]


def test_keyed_art_ships_every_plate_it_names():
    """The .pro embeds an absolute file:// URL, so a missing asset is a blank slide at church."""
    for path, _ in styles.KEYED_ART.values():
        assert Path(path).exists(), path


def test_only_the_camera_annotating_sections_get_a_keyed_label(tmp_path):
    """The sections Keynote gives a keyed label *and no navy plate* — measured off the approved
    deck. Ones it gives both (봉 헌, 교회 소식, 예배의 부름, 축도) keep the plate here (#234)."""
    pres = build.load(build.build(_service_data(), str(tmp_path / "week.pro"))[0])

    for name in ("회개로의 초대", "죄사함의 선포", "합심 기도"):
        cues = _cues_of(pres, name)
        assert len(cues) == 2, name  # both placements, operator picks by camera framing
        slides = [_slide_of_cue(c) for c in cues]
        assert all(_green(s) and "m1-angled-bar" in _images_of(s) for s in slides)
        assert {s.elements[0].element.bounds.origin.y for s in slides} == {
            styles.KEYED_LABEL_PLACEMENTS[p][0][1] for p in ("top", "bottom")
        }

    for name in ("봉 헌", "교회 소식", "예배의 부름", "축도"):
        plate = _slide_of_cue(_cues_of(pres, name)[0])
        assert not _green(plate), name
        assert _has_frame(plate), name


def test_the_opening_section_ends_on_a_green_park(tmp_path):
    """Keynote's slide 5 held a 예배 준비 안내 message here; the operator replaced it with a blank
    green (#178 review). The deck waits on this cue while people come in, and green keys the live
    camera through where a navy card would cover it."""
    pres = build.load(build.build(_service_data(), str(tmp_path / "week.pro"))[0])
    cues = _cues_of(pres, "예배 시작")

    assert _green(_slide_of_cue(cues[-1]))
    assert not _slide_of_cue(cues[-1]).elements


def test_offering_divider_shows_the_hymn_title_and_number(tmp_path):
    pres = build.load(build.build(_service_data(), str(tmp_path / "week.pro"))[0])
    text = _rtf_text(_slide_of_cue(_cues_of(pres, "봉 헌")[0]))

    assert rtf.escape("피난처 있으니") in text
    assert rtf.escape("(찬 70장)") in text


def test_build_survives_hymn_images_it_cannot_place_yet(tmp_path):
    """The downloaded 봉 헌 pages are #179. Until they land the section is title-only — a build
    must not die on another issue's stub, or every weekly deck goes down with it."""
    data = _service_data(offering_hymn_images=["/tmp/page-1.png", "/tmp/page-2.png"])
    pres = build.load(build.build(data, str(tmp_path / "week.pro"))[0])

    assert len(_cues_of(pres, "봉 헌")) == 1
    with pytest.raises(NotImplementedError):
        build.fill_offering_hymn(pres, "70", "피난처 있으니", data.offering_hymn_images)


def test_sermon_extra_refs_each_get_their_own_group(tmp_path):
    """#114 passages typed in review; an empty one (lookup failed at save) is skipped."""
    data = _service_data(
        sermon_extra_refs=["요 3:16", "롬 8:28"],
        sermon_extra_passages=[[_verse(16, "하나님이 세상을 이처럼 사랑하사", "For God so loved")], []],
    )
    pres = build.load(build.build(data, str(tmp_path / "week.pro"))[0])

    assert "요 3:16" in _group_names(pres)
    assert "롬 8:28" not in _group_names(pres)


def test_sending_song_is_fixed_content_sung_before_both_closing_elements(tmp_path):
    pres = build.load(build.build(ServiceData(), str(tmp_path / "empty.pro"))[0])
    cues = _cues_of(pres, "파송의 노래")
    cards = [_rtf_text(_slide_of_cue(c)) for c in cues]

    # The plate, then each cue card as a keyed label in both placements (#234).
    assert len(cues) == 5
    assert all(rtf.escape("축도 전 찬양") in c for c in cards[1:3])
    assert all(rtf.escape("주기도문 전 찬양") in c for c in cards[3:5])
    assert _group_names(pres).count("축복의 통로") == 1


def test_generated_deck_writes_no_arrangement_and_no_web_element(tmp_path):
    """Two closed decisions a whole-deck build could quietly reopen: song sections stay slide
    labels rather than an Arrangement (#176), and Glossa is a Prop the generator never emits
    (#177)."""
    pres = build.load(build.build(_service_data(), str(tmp_path / "week.pro"))[0])

    assert not pres.arrangements and not pres.selected_arrangement.string
    assert not any(
        e.element.fill.media.HasField("web_content")
        for cue in pres.cues
        for e in _slide_of_cue(cue).elements
    )


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
    the generator must not write one at all. Decks instead inherit the global cut transition
    set in the ProPresenter UI (#174, closed: no deck-level transition, ever)."""
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


# ── Legibility + Keynote parity (#178 review) ─────────────────────────────────

def _images_of(slide) -> list[str]:
    return [e.element.name for e in slide.elements if e.element.fill.HasField("media")]


def test_body_type_is_sized_for_the_congregation():
    """A large share of the congregation is elderly, and the #189 sample PNGs turned out to be
    drawn at mock-up scale. These floors are the church's own Keynote deck on the same
    1920×1080 canvas (주일 2부-2026-08-30-v1.key slides 58, 123, 81, 1) — the generated deck must
    never quietly drop below what the operator already approved."""
    assert styles.VERSE_KO.size >= 84       # master slide 58, 개역한글 body
    assert styles.VERSE_EN.size >= 59       # master slide 58, ESV body
    # The [ref, 개역한글] labels are deliberately *not* held to a legibility floor: they are
    # reference furniture in their own small boxes above each body, and every point they take
    # is a point of body the congregation loses (#178 review).
    assert styles.ANNOUNCE_TITLE.size >= 72     # master slides 123–131 are one 80pt box
    assert styles.ANNOUNCE_DETAIL.size >= 60
    assert styles.LITURGY_BODY.size >= 72   # master slide 81, 사도신경
    assert styles.SERVICE_HEADING.size >= 130   # master slide 1, N부 예배를 시작합니다


def test_a_long_announcement_shrinks_to_fit_rather_than_overflowing():
    """ProPresenter's own SCALE_FONT_DOWN shrinks until the text fits *without wrapping* — it
    put a four-line verse on one ~20pt line on PP 21.4 — so the fitting happens at authoring
    time instead. A short item keeps the full type scale."""
    short_item = "3. 제직회\n\n오늘 1:30 PM 친교실에서 제직회가 있습니다."
    long_item = "6. 한국학교 개강 안내\n\n" + "9/20 주일 1:20 개강합니다. " * 20
    nominal = f"\\fs{round(styles.ANNOUNCE_TITLE.size * 2)} "

    assert nominal in _rtf_text(styles.announcement("교회 소식", [short_item]))
    assert nominal not in _rtf_text(styles.announcement("교회 소식", [long_item]))


def test_long_liturgy_and_cards_are_fitted_to_their_boxes():
    """The fixed-wording slides have no chunker behind them — 사도신경 and the 환영 card are as
    long as the church wrote them — so every one must be measured against the box it lands in."""
    _, _, w, h = styles.CONTENT_RECT

    for lines in content.APOSTLES_CREED_RESPONSIVE + content.APOSTLES_CREED + content.LORDS_PRAYER:
        runs = styles._scaled([("\n".join(lines), styles.LITURGY_BODY)], w, h - 110.0)
        assert styles._wrapped_height(runs, w, 1.0) <= h - 110.0

    for card in (content.MOTTO, content.WELCOME_CARD, content.CLOSING_NOTE):
        # A card line may be a (gold, white) pair that splits mid-line; either way it is one line.
        flat = ["".join(ln) if isinstance(ln, tuple) else ln for ln in card]
        runs = styles._scaled([("\n".join(flat), styles.CARD_BODY)], w, h - 160.0)
        assert styles._wrapped_height(runs, w, 1.0) <= h - 160.0


def test_opening_group_carries_the_logo_and_the_two_pre_service_photos(tmp_path):
    """master.key opens on the logo'd plates, the 표어 card and two full-bleed photos (slides
    4–5). None of it is in ServiceData, so the generator ships the artwork itself."""
    pres = build.load(build.build(_service_data(), str(tmp_path / "week.pro"))[0])
    slides = [_slide_of_cue(c) for c in _cues_of(pres, "예배 시작")]

    assert _images_of(slides[0]) == ["npc-logo"]          # 1부 opening plate
    assert _images_of(slides[2]) == ["npc-logo"]          # 교회 표어 card
    assert [_images_of(s)[0] for s in slides[3:5]] == ["pre-service-church", "pre-service-welcome"]
    assert all(Path(p).exists() for p in styles.PRE_SERVICE_IMAGES)
    assert Path(styles.LOGO).exists()


def test_opening_plate_stacks_date_heading_title_notice_like_the_keynote_deck():
    """Same reading order and rhythm as master.key slide 1 — the plate the operator compares
    side by side with the deck they are replacing."""
    slide = styles.service_intro("1부", "한 사람의 용기", "[삼상 14:1-23]", "2026년 8월 30일")
    stacked = sorted(
        (e.element.bounds.origin.y, e.element.text.rtf_data.decode())
        for e in slide.elements
        if e.element.text.rtf_data
    )

    assert len(stacked) == 4
    assert rtf.escape("2026년 8월 30일") in stacked[0][1]
    assert rtf.escape("1부 예배를 시작합니다.") in stacked[1][1]
    assert rtf.escape("한 사람의 용기") in stacked[2][1]
    assert rtf.escape("[삼상 14:1-23]") in stacked[2][1]
    assert rtf.escape(content.OPENING_NOTICE) in stacked[3][1]


def test_choir_title_is_a_lower_third_banner_not_a_full_screen_plate(tmp_path):
    """master.key slide 89 shows the choir's title as the same keyed strip the lyrics use. A
    full-screen plate there read as a second divider and broke the section's rhythm."""
    pres = build.load(build.build(_service_data(), str(tmp_path / "week.pro"))[0])
    title = _slide_of_cue(_cues_of(pres, "성가대 찬양")[1])

    assert _green(title)
    assert rtf.escape("사랑은") in _rtf_text(title)
    assert title.elements[0].element.text_line_mask.enabled


def test_the_verse_slide_lays_out_inside_the_content_rect():
    """Every box a scripture slide draws must sit inside the content rect, in reading order.

    ``verse_rects`` fixes the four heights from the type scale and hands whatever is left to
    the gaps, so a type-scale or frame-inset change that no longer fits has to fail here rather
    than be found in ProPresenter — which does not reflow, it clips (#178 review).
    """
    x, y, w, h = styles.CONTENT_RECT
    rects = styles.verse_rects()

    for key in ("ko_label", "ko_body", "en_label", "en_body"):
        bx, by, bw, bh = rects[key]
        assert (bx, bw) == (x, w)
        assert by >= y and by + bh <= y + h + 0.5, f"{key} runs past the content rect"

    ko_bottom = rects["ko_body"][1] + rects["ko_body"][3]
    assert ko_bottom <= rects["rule_y"][0] <= rects["en_label"][1]


def test_the_packer_and_the_slide_builder_share_one_set_of_boxes():
    """The chunker's promise ("this many verses fit") is only as good as its idea of the box.
    They were separate derivations until #178, where the builder's boxes were a label-line
    smaller than what the packer had budgeted, and the overflow landed on the operator."""
    rects = styles.verse_rects()
    assert build._verse_boxes() == (rects["ko_body"][2:], rects["en_body"][2:])


def test_a_packed_passage_ships_wholly_at_the_reference_size():
    """The operator's rule for scripture: never clip, and keep one size throughout — split a
    long passage across more slides instead of shrinking it (#178 review). So no cue the packer
    produced may come back at anything other than the nominal 84/59.
    """
    verses = [
        Verse(**_verse(
            n,
            "때가 이르매 예수께서 사도들과 함께 앉으사 이르시되 내가 고난을 받기 전에 너희와 함께 이 유월절 먹기를 원하고 원하였노라",
            "And when the hour came, he reclined at table, and the apostles with him, and he "
            "said to them, I have earnestly desired to eat this Passover with you before I "
            "suffer.",
        ))
        for n in range(14, 25)
    ]

    pres = build.new_presentation("x")
    build.fill_verse_slides(pres, "말씀", "눅 22:14-24", verses)

    for cue in pres.cues[1:]:  # cue 0 is the section divider
        text = _rtf_text(cue.actions[0].slide.presentation.base_slide)
        assert f"\\fs{round(styles.VERSE_KO.size * 2)} " in text
        assert f"\\fs{round(styles.VERSE_EN.size * 2)} " in text


def test_a_text_block_is_budgeted_with_the_leading_after_its_last_line():
    """ProPresenter reserves a paragraph's line spacing after the *final* line, not only between
    lines — so an N-line block costs N × (pitch + leading), not N × pitch + (N-1) × leading.

    This is worth a test of its own because the shortfall is under one line: it never looks like
    an overflow, the slide just quietly wears the app's "text box too small" flag. It was found
    by measuring two decks the operator had flagged by hand (#178 review), and
    ``scripts/audit_pro_layout.py`` applies the same rule.
    """
    style = replace(styles.VERSE_KO, size=100.0, line_spacing=20.0)
    per_line = 100.0 * layout.LINE_PITCH + 20.0

    one = styles._wrapped_height([("가", style)], 4000.0, 1.0)
    three = styles._wrapped_height([("가\n나\n다", style)], 4000.0, 1.0)

    assert one == pytest.approx(per_line)
    assert three == pytest.approx(3 * per_line)


def test_the_opening_plate_title_has_room_for_its_trailing_leading():
    """The 2026-08-30 plate — a 100pt sermon title over an 88pt reference — is the tightest
    fixed box in the deck, and the box that survived the first review round still warned."""
    runs = [("한 사람의 용기와 믿음의 파급력\n", styles.SERVICE_TITLE),
            ("[삼상 14:1-23]", styles.SERVICE_REF)]
    assert styles._fit_scale(runs, 1480.0, 262.0) == 1.0
