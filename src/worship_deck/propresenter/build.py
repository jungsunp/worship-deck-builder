"""Ground-up ProPresenter ``.pro`` generator (v3 migration, epic #184).

**Complete**: the protobuf primitives (#172), the sung-lyric fillers (#175), ``build()``
and the verse/announcement/choir/liturgy fills (#178), and the 봉헌 hymn pages (#179).
See ``docs/propresenter-generator-design.md`` for the design rationale and the decoded
``.pro`` anatomy these primitives are built from.

How this differs from the Keynote builder it replaces:

* **Ground-up, not template mutation.** ``build()`` serializes a *fresh*
  ``rv.data.Presentation`` from the assembled ``ServiceData`` each week — there is
  no landmark detection (no ``anchors.py`` analog) and no surgical in-place edit.
* **No back-to-front index arithmetic.** Keynote fills sections highest-index-first
  so slide duplication doesn't shift unfilled anchors. Here each ``fill_*`` simply
  *appends* cues + a ``CueGroup`` in service order, top to bottom.
* **No macOS/Keynote/AppleScript.** The primitives are pure protobuf; a ``.pro`` is
  a single raw-serialized ``Presentation`` message (no zip container) — read/write
  is ``read_bytes`` / ``write_bytes`` (see ``roundtrip.py``).

**Styling is baked, not referenced.** ProPresenter has no runtime theme reference on
a slide (``PresentationSlide`` carries no theme field, and ``Action.SlideType`` has
``reserved "template"``); font/color/size live on each element. #170 closed on that
finding: there is no authored style-kit deck to clone, so each slide's look is baked
from the code-defined values in ``styles.py`` (the #189/#168 interim pick), composed
out of ``elements.py`` and ``rtf.py``.

Output: one weekly ``.pro`` the operator imports and clicks through — the direct
analog of today's single ``.key``. Service sections become ProPresenter *groups*.
"""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

# Import order is load-bearing here; sorting it moves `pb` below the *_pb2 imports that
# depend on its side effect, and the module then fails to import.
# isort: off
from . import pb  # noqa: F401 -- side effect: puts pb/ on sys.path for the bare *_pb2 imports

import action_pb2
import cue_pb2
import presentation_pb2
import slide_pb2
import uuid_pb2
import url_pb2

# isort: on
from worship_deck.bible import layout
from worship_deck.bible.verses import Verse, verse_labels
from worship_deck.hymn import PRO_DESIGN
from worship_deck.lyrics import linebreak
from worship_deck.lyrics.transcribe import Song, arranged_chunks
from worship_deck.parse import ServiceData

from . import announce, content, elements, rtf, styles

# The dev/church ProPresenter build the vendored protos are pinned to (#191 re-pins to 18.4).
PP_VERSION = (21, 4)

# Service order, top to bottom — the fixed liturgy sequence build() walks. Weekly groups draw
# from ServiceData; the fixed-wording groups (사도신경 creed, 주기도문 prayer, dividers) come from
# content.py. This replaces anchors.py's landmark detection with a plain declared order.
# (Documented here for the reader; build() wires these to the fill_* calls in #180.)


# ── Entry point ───────────────────────────────────────────────────────────────

def build(data: ServiceData, out_pro: str) -> tuple[str, dict[str, float]]:
    """Serialize ``data`` into a single weekly ``.pro`` at ``out_pro``.

    Mirrors ``keynote.build.build(data, template, out)`` but ground-up: create a fresh
    ``Presentation``, walk the service order calling each ``fill_*`` — each appends its cues
    plus one ``CueGroup`` — and ``serialize`` the whole message. Returns ``(out_pro, steps)``
    where ``steps`` is per-section timing, for ``obs.run_record``.

    The order below **is** the liturgy: there is no ``anchors.py`` analog here, and no
    back-to-front index arithmetic, because nothing shifts when a section grows. Weekly
    sections are skipped when their ``ServiceData`` field is empty (as Keynote does); the
    fixed-wording sections from ``content.py`` always emit, because in a ground-up deck
    nothing rides along for free the way ``master.key``'s untouched slides do.

    Two deliberate departures from the template: the duplicated 예배의 부름 / 회개로의 초대 /
    죄사함의 선포 / 환영 및 인사 / 합심 기도 heading slides are emitted once rather than two or
    three times, and the stale leftover intro slide at the deck's end is dropped.
    """
    steps: dict[str, float] = {}

    def _t(name: str, fn, *args, **kwargs):  # type: ignore[no-untyped-def]
        t = time.monotonic()
        result = fn(*args, **kwargs)
        steps[name] = round(time.monotonic() - t, 3)
        return result

    labels = content.DIVIDER_LABELS
    pres = new_presentation(Path(out_pro).stem)
    _t("opening", fill_date, pres, data.date, data.sermon_title, data.sermon_ref)
    if data.worship_songs:
        _t("worship_songs", fill_worship_songs, pres, data.worship_songs)
    if data.call_to_worship_passage:
        _t(
            "call_to_worship", fill_verse_slides, pres, labels["call_to_worship"],
            data.call_to_worship_ref, [Verse(**v) for v in data.call_to_worship_passage],
        )
    _t("repentance_call", fill_divider, pres, labels["repentance_call"])
    _t("absolution", fill_divider, pres, labels["absolution"])
    if data.confession_song:
        _t("confession", fill_confession, pres, data.confession_song)
    _t("apostles_creed", fill_creed, pres)
    if data.choir_song:
        _t("choir", fill_choir, pres, data.choir_song)
    # 봉 헌: the divider carrying this week's hymn title + number, then the downloaded hymn
    # pages. Unconditional — the hymn download is best-effort, so the divider has to emit even
    # when it produced nothing (#179).
    _t(
        "offering_hymn", fill_offering_hymn, pres, data.offering_hymn_number,
        data.offering_hymn_title, data.offering_hymn_images,
    )
    _t("welcome", fill_divider, pres, labels["welcome"])
    if data.announcements:
        _t("announcements", fill_announcements, pres, data.announcements)
    _t("united_prayer", fill_divider, pres, labels["united_prayer"])
    if data.sermon_title or data.sermon_passage:
        _t(
            "sermon", fill_sermon, pres, data.sermon_title, data.sermon_ref,
            [Verse(**v) for v in data.sermon_passage],
        )
    if data.sermon_extra_refs:
        _t("sermon_extra", fill_sermon_extra, pres, data.sermon_extra_refs, data.sermon_extra_passages)
    if data.worship_after_sermon:
        _t("worship_after_sermon", fill_song, pres, data.worship_after_sermon)
    _t("sending", fill_sending, pres)
    _t("benediction", fill_divider, pres, labels["benediction"])
    _t("lords_prayer", fill_liturgy, pres, labels["lords_prayer"], content.LORDS_PRAYER)
    _t("ending", fill_ending, pres, data.date)

    _t("serialize", serialize, pres, out_pro)
    return out_pro, steps


# ── Per-section fillers (mirror keynote/build.py fill_*) ──────────────────────
# Each appends its slide cues to ``pres.cues`` and one ``CueGroup`` (label + color) to
# ``pres.cue_groups``, referencing the cues by UUID. No return-count bookkeeping is needed
# (unlike Keynote): nothing downstream shifts.

def _group(
    pres: presentation_pb2.Presentation, label: str, cue_uuids: list[uuid_pb2.UUID]
) -> None:
    """Close a section: one ``CueGroup`` named ``label`` in its section color."""
    add_group(pres, label, styles.GROUP_COLORS.get(label), cue_uuids)


def fill_date(
    pres: presentation_pb2.Presentation, date: str, sermon_title: str, ref: str = ""
) -> None:
    """예배 시작 — the opening plates. Analog of ``set_date_slides``' intro half.

    One deck serves both services, so the opening plate exists once per
    ``content.SERVICE_PARTS`` entry, followed by the 표어 card, the two full-bleed pre-service
    plates (master slides 4–5, shipped as ``styles.PRE_SERVICE_IMAGES``) — fixed content that
    rode along untouched inside ``master.key`` and has to be authored here.

    The section ends on a blank green cue, where Keynote's slide 5 held a 예배 준비 안내 card. The
    operator dropped that message restyling a draft (#178 review, round 3): the deck sits here
    while people come in, and green keys the live camera through instead of covering it.
    """
    cue_uuids = [
        add_cue(pres, new_slide("service_intro", part, sermon_title, ref, date), f"{part} 시작")
        for part in content.SERVICE_PARTS
    ]
    cue_uuids.append(add_cue(pres, new_slide("text_card", content.MOTTO), "교회 표어"))
    for path in styles.PRE_SERVICE_IMAGES:
        cue_uuids.append(add_cue(pres, new_slide("image", path), Path(path).stem))
    cue_uuids.append(add_cue(pres, new_slide("blank_green"), ""))
    _group(pres, content.DIVIDER_LABELS["opening"], cue_uuids)


def fill_ending(pres: presentation_pb2.Presentation, date: str) -> None:
    """예배 마침 — closing plate per service part, then the 폐회 안내 card."""
    cue_uuids = [
        add_cue(pres, new_slide("service_outro", part, date), f"{part} 마침")
        for part in content.SERVICE_PARTS
    ]
    cue_uuids.append(add_cue(pres, new_slide("text_card", content.CLOSING_NOTE), "폐회 안내"))
    _group(pres, content.DIVIDER_LABELS["ending"], cue_uuids)


def _keyed_cues(pres: presentation_pb2.Presentation, label: str) -> list[uuid_pb2.UUID]:
    """Both placements of a keyed label, top-left and bottom-centre (#234).

    Keynote carries one placement per service part. Here they are not about service parts at all:
    the operator picks whichever clears the live shot, which depends on how the camera is framed,
    so both ship and they hold on the one they want.
    """
    return [
        add_cue(pres, new_slide("keyed_label", label, placement), f"{label} ({korean})")
        for placement, korean in (("top", "위"), ("bottom", "아래"))
    ]


def fill_divider(pres: presentation_pb2.Presentation, label: str, subtitle: str = "") -> None:
    """A heading-only section: 회개로의 초대, 죄사함의 선포, 환영 및 인사, 합심 기도, 축도, 봉 헌.

    These carry no weekly content at all — under Keynote they were simply slides nobody edited.
    The template repeats several of them two or three times (a heading slide per service part);
    one navy plate is enough in ProPresenter, where the operator holds on a cue rather than
    clicking past duplicates.

    ``content.KEYED_SECTIONS`` gets a keyed label over the live camera instead of that plate
    (#234) — see the note there for which sections and why. None of them carries a subtitle.
    """
    if label in content.KEYED_SECTIONS:
        _group(pres, label, _keyed_cues(pres, label))
        return
    cue_uuid = add_cue(pres, new_slide("section_divider", label, subtitle), label)
    _group(pres, label, [cue_uuid])


def _chunks(song: Song) -> list[tuple[str, list[str]]]:
    """The song's ``(section label, ≤2 lines)`` slides, in play order (#175).

    Two Korean lines per slide is what the church shows today and what the #189 samples are
    drawn at — a lower-third over the live band only has room for that much. So the grouping is
    ``lyrics.transcribe.arranged_chunks`` unchanged; what is ProPresenter-specific is
    *re-breaking first*.

    ``linebreak.rebreak`` runs at assemble time, but only over gasazip lookups — choir pastes,
    typed lyrics, library songs and anything the operator edited in review reach the builder
    unbroken. Keynote survives that (its banners autoshrink); here ``styles.worship_lyric_ko``
    sizes its strip block from ``len(lines)``, so an over-long line wraps inside a box measured
    for fewer lines and the last line is clipped. Same cap as Keynote (22 chars — the strips
    hug the text, and a wider line reads as a full-bleed bar), applied a second time here.
    """
    song = replace(
        song,
        lines=linebreak.rebreak(song.lines),
        sections=[{**s, "lines": linebreak.rebreak(s["lines"])} for s in song.sections],
    )
    return arranged_chunks(song)


def fill_worship_songs(pres: presentation_pb2.Presentation, songs: list[dict]) -> None:
    """찬양 medley — one keyed title banner + lyric group per song (#175).

    Each song gets the next color in ``styles.SONG_COLORS``: the weekly deck is one flat list of
    group bars, so a distinct hue per song is what marks where one ends and the next begins.
    """
    for i, song in enumerate(songs):
        fill_song(pres, song, styles.SONG_COLORS[i % len(styles.SONG_COLORS)])


def fill_song(
    pres: presentation_pb2.Presentation,
    song: dict,
    color: tuple[int, int, int] | None = None,
) -> None:
    """One song: a keyed title banner, its ≤2-line lyric slides, and a trailing blank (#175).

    Shared by the worship medley and 고백의 찬양. Everything sits over the live camera, so all
    three slide kinds are chroma-green backed; the trailing ``blank_green`` is what the operator
    arrows onto between songs (ProPresenter's Clear blanks to black and drops the key).

    The whole song is one ``CueGroup`` named after it, colored by ``color`` (the medley cycles
    ``styles.SONG_COLORS`` so songs read apart). When ``song['sections']`` is populated
    (operator-labeled V1/C/B, #113) the lyrics play in arrangement order and each lyric cue
    carries its label as a colored ProPresenter **slide label**, so the V1/C/B structure stays
    readable in the grid without any of it becoming a group.

    Giving each label its own group + a real ``Arrangement`` was built and measured under #176 and
    **rejected**: ProPresenter groups do not nest (``Group`` has no parent field), so section bars
    end up siblings of the song bar — collapsing a song leaves them open, and the weekly medley
    went from 5 bars to 18 for a volunteer to navigate. See design doc Decision 4; don't redo it.

    An empty ``lines`` yields banner + blank only.
    """
    parsed = Song(**song)
    add_group(pres, parsed.title, color or styles.GROUP_COLORS["찬양"], _song_cues(pres, parsed))


def _song_cues(pres: presentation_pb2.Presentation, parsed: Song) -> list[str]:
    """The cues of one song — banner, lyrics, trailing blank — without the group around them.

    Split out so 고백의 찬양 can fold them into its own group instead of opening a second one.
    """
    cue_uuids = [add_cue(pres, new_slide("song_banner", parsed.title), parsed.title)]
    for label, lines in _chunks(parsed):
        cue_uuids.append(
            add_cue(pres, new_slide("worship_lyric_ko", lines), label, styles.section_color(label))
        )
    cue_uuids.append(add_cue(pres, new_slide("blank_green"), ""))
    return cue_uuids


def fill_confession(pres: presentation_pb2.Presentation, song: dict) -> None:
    """고백의 찬양 — full-screen divider + blank, then the song's banner + lyrics (#175).

    Mirrors ``keynote.build.fill_confession_slides``: the divider carries the section heading
    over the week's song title, and the rest of the section is exactly a worship-song unit, so it
    reuses ``_song_cues``. **One** group, not two — the divider and the song it announces are a
    single section to the operator, and two bars for one section is two things to find under
    pressure (#178 review, round 3). The medley is the exception: there each song is genuinely
    its own section.
    """
    label = content.DIVIDER_LABELS["confession_song"]
    parsed = Song(**song)
    cue_uuids = [
        add_cue(pres, new_slide("section_divider", label, parsed.title), label),
        add_cue(pres, new_slide("blank_green"), ""),
    ]
    add_group(pres, label, styles.GROUP_COLORS[label], cue_uuids + _song_cues(pres, parsed))


def fill_choir(pres: presentation_pb2.Presentation, song: dict) -> None:
    """성가대 찬양 — divider (carrying the booth's lighting cue as a slide note), the song's
    keyed title banner, then the keyed lyric slides.

    The divider is the full-screen plate that announces the choir, with the composer credit; the
    title itself is a ``song_banner`` — the same lower-third strip the lyrics use, over the live
    choir shot, exactly as master.key slide 89 has it. It was a full-screen plate in the first
    cut of this generator, which read as a second divider and broke the lower-third rhythm of the
    section (#178 review). The lyrics and the trailing blank are green for the same reason.
    """
    label = content.DIVIDER_LABELS["choir_song"]
    parsed = Song(**song)
    subtitle = parsed.title
    if parsed.composer:
        subtitle += f"  {parsed.composer}"
    cue_uuids = [
        add_cue(
            pres,
            new_slide("section_divider", label, subtitle),
            label,
            note=content.CHOIR_LIGHT_NOTE,
        ),
        add_cue(pres, new_slide("song_banner", parsed.title), parsed.title),
    ]
    for section_label, lines in _chunks(parsed):
        cue_uuids.append(
            add_cue(
                pres,
                new_slide("worship_lyric_ko", lines),
                section_label,
                styles.section_color(section_label),
            )
        )
    cue_uuids.append(add_cue(pres, new_slide("blank_green"), ""))
    _group(pres, label, cue_uuids)


def _verse_boxes() -> tuple[tuple[float, float], tuple[float, float]]:
    """The (width, height) of the 개역한글 and ESV body blocks on a ``verse_fullscreen`` slide.

    Keynote measures these off the open template (``read_verse_boxes``); here the layout is
    baked, so both the packer and the builder read them from ``styles.verse_rects()`` — the
    reference labels live in their own boxes, so the whole of each body box is the budget.
    """
    rects = styles.verse_rects()
    return (rects["ko_body"][2:], rects["en_body"][2:])


def _pitch(style: styles.Style) -> float:
    """A line's vertical advance: ``LINE_PITCH`` × the font, plus the style's extra leading.

    The font itself claims more room than its point size — 1.21× for Apple SD Gothic Neo — so
    budgeting a line at ``size + line_spacing`` overruns every box by ~13% and lands the
    passage in ProPresenter's "text is too large" state (#178 review).
    """
    return style.size * layout.LINE_PITCH + style.line_spacing


def _verse_cues(
    pres: presentation_pb2.Presentation, ref: str, verses: list[Verse]
) -> list[uuid_pb2.UUID]:
    """One ``verse_fullscreen`` cue per packed chunk of ``verses``, labelled with ``ref``."""
    ko_label, en_label = verse_labels(ref)
    ko_box, en_box = _verse_boxes()
    chunks = layout.chunk_verses(
        verses,
        ko_box=ko_box,
        en_box=en_box,
        ko_font=styles.VERSE_KO.size,
        en_font=styles.VERSE_EN.size,
        ko_line_h=_pitch(styles.VERSE_KO) / styles.VERSE_KO.size,
        en_line_h=_pitch(styles.VERSE_EN) / styles.VERSE_EN.size,
    )
    return [
        add_cue(
            pres,
            new_slide(
                "verse_fullscreen",
                ko_label,
                [(v.number, v.korean) for v in chunk],
                en_label,
                [(v.number, v.english) for v in chunk],
            ),
            f"{chunk[0].number}-{chunk[-1].number}" if len(chunk) > 1 else str(chunk[0].number),
        )
        for chunk in chunks
    ]


def fill_verse_slides(
    pres: presentation_pb2.Presentation, group_label: str, ref: str, verses: list[Verse]
) -> None:
    """Bilingual scripture (예배의 부름) — a divider carrying the reference, then 개역한글 + ESV
    bodies packed to a consistent density. Full-screen: these replace the camera.

    The passage is split across cues by ``bible.layout.chunk_verses``, the same packing model
    the Keynote builder uses (#115) — fed this deck's baked box sizes instead of measured ones.
    """
    cue_uuids = [
        add_cue(pres, new_slide("section_divider", group_label, ref), group_label)
    ]
    cue_uuids += _verse_cues(pres, ref, verses)
    _group(pres, group_label, cue_uuids)


def fill_sermon(
    pres: presentation_pb2.Presentation, title: str, ref: str, verses: list[Verse]
) -> None:
    """말씀 — the reference plate, the reading, the sermon-title plate, then a green blank.

    That trailing ``blank_green`` is load-bearing, not padding. The ATEM keys ProPresenter's
    output, and a cleared output is *black*, which keys nothing and covers the camera — so the
    operator parks on a real green cue for the length of the sermon, and the Glossa prop (#177)
    composites its live translation over the shot. There is nothing else on screen during the
    preaching: per #184 the sermon runs without verse plates.
    """
    label = content.DIVIDER_LABELS["sermon"]
    cue_uuids: list[uuid_pb2.UUID] = []
    if ref:
        _, en_label = verse_labels(ref)
        cue_uuids.append(add_cue(pres, new_slide("section_divider", ref, en_label), label))
    cue_uuids += _verse_cues(pres, ref, verses) if verses else []
    if title:
        cue_uuids.append(
            add_cue(pres, new_slide("song_title", title, ref), title)
        )
    cue_uuids.append(add_cue(pres, new_slide("blank_green"), ""))
    _group(pres, label, cue_uuids)


def fill_announcements(pres: presentation_pb2.Presentation, items: list[str]) -> None:
    """교회 소식 — the divider, the 표어/환영 card, then the week's notices.

    Each item arrives from the bulletin parser (and then the review editor) as
    ``"N. title\\n\\ndetail"``. ``announce.parse_item`` lifts its 날짜/장소/문의 out of the prose
    into the plate's rail, and ``styles.split_announcement`` cuts anything too long for one plate
    across two rather than shrinking the type under it (#233) — so a notice can own more than one
    cue, and the continuations are labelled as such in the operator's cue list.
    """
    label = content.DIVIDER_LABELS["announcements"]
    cue_uuids = [
        add_cue(pres, new_slide("section_divider", label), label),
        add_cue(pres, new_slide("text_card", content.WELCOME_CARD, (2,)), "환영"),
    ]
    for number, block in enumerate(items, start=1):
        item = announce.parse_item(block)
        for part_index, part in enumerate(styles.split_announcement(item)):
            cue_uuids.append(add_cue(
                pres,
                new_slide("announcement", label, part, number, len(items)),
                item.title if not part_index else f"{item.title} (계속)",
            ))
    _group(pres, label, cue_uuids)


def _hymn_subtitle(number: str, title: str) -> str:
    """The 봉 헌 divider's subtitle: ``"피난처 있으니  (찬 70장)"`` (master slide 97)."""
    parts = [title] if title else []
    if number:
        parts.append(f"(찬 {number}장)")
    return "  ".join(parts)


def _pro_hymn_images(image_paths: list[str]) -> list[str]:
    """Swap the operator-kept ``no-bg`` hymn pages for their ``hymn.PRO_DESIGN`` siblings (#179).

    The review app downloads and prunes the ``no-bg`` set (``data/runs/<date>/hymn/slide-N.png``)
    and the assemble step fetches the same hymn again into a ``<design>/`` subdirectory beside it.
    Both renders come from the same source PPTX, so they have the same page count and the same
    ``pdftoppm`` filenames — matching by filename means the operator's pruning carries over for
    free, with no second list to keep in sync. Falls back to the given page when the sibling is
    missing, so a failed design fetch degrades to the white pages rather than to no 봉헌 at all.
    """
    out = []
    for path in image_paths:
        sibling = Path(path).parent / PRO_DESIGN / Path(path).name
        out.append(str(sibling) if sibling.exists() else path)
    return out


def fill_offering_hymn(
    pres: presentation_pb2.Presentation, number: str, title: str, image_paths: list[str]
) -> None:
    """봉헌 — the divider, then the downloaded hymn pages as full-bleed image cues (#179).

    **One** group covering divider + pages, like ``fill_confession`` — the heading announcing
    this week's hymn and the hymn itself are a single section to the operator (#178 review,
    round 3). The divider emits even when ``image_paths`` is empty: the hymn download is
    best-effort, and a number/title with no pages still tells the operator what to sing, exactly
    as ``keynote.build`` fills the title slide independently of the image block.

    No trailing ``blank_green``: 봉헌 is a full-screen section — the ATEM cuts to the Mac mini
    rather than keying these over the live camera — so the pages stay opaque.
    """
    label = content.DIVIDER_LABELS["offering_hymn"]
    cue_uuids = [
        add_cue(pres, new_slide("section_divider", label, _hymn_subtitle(number, title)), label)
    ]
    for i, path in enumerate(_pro_hymn_images(image_paths), 1):
        name = f"찬 {number}장 {i}" if number else f"봉헌 {i}"
        cue_uuids.append(add_cue(pres, new_slide("image", path), name))
    _group(pres, label, cue_uuids)


def fill_creed(pres: presentation_pb2.Presentation) -> None:
    """사도신경 — the 문답 form, a green break, then the traditional recitation.

    Both forms the deck carries ship and the operator uses whichever the service calls for (#178).
    The green cue between them is the boundary, and it is load-bearing the same way
    ``fill_sermon``'s is: ProPresenter's Clear blanks to **black**, which keys nothing and covers
    the camera, so the operator needs a real green cue to park on while the unused form is
    skipped past. It is the one place a full-screen section carries green — a break *between*
    forms, not content — so the design doc's "full-screen sections stay opaque navy" rule holds
    everywhere else (#244).

    The two forms are also named apart in the grid (`사도신경 문답 1`–`3` / `사도신경 1`–`2`);
    they used to run together as `사도신경 1`–`5`, which told the operator nothing about where
    one form ended.
    """
    label = content.DIVIDER_LABELS["apostles_creed"]
    cue_uuids = [add_cue(pres, new_slide("section_divider", label), label)]
    for i, (question, answer) in enumerate(content.APOSTLES_CREED_RESPONSIVE, 1):
        cue_uuids.append(
            add_cue(
                pres,
                new_slide("liturgy_responsive", label, question, answer),
                f"{label} 문답 {i}",
            )
        )
    cue_uuids.append(add_cue(pres, new_slide("blank_green"), ""))
    for i, lines in enumerate(content.APOSTLES_CREED, 1):
        cue_uuids.append(add_cue(pres, new_slide("liturgy", label, lines), f"{label} {i}"))
    _group(pres, label, cue_uuids)


def fill_liturgy(
    pres: presentation_pb2.Presentation, group_label: str, slides: list[list[str]]
) -> None:
    """Fixed-wording liturgy from ``content.py`` — 주기도문 (사도신경 has its own ``fill_creed``).

    ``slides`` is one list of lines per cue — the wording is split exactly where the church's
    own deck breaks it, because the congregation reads along.
    """
    cue_uuids = [add_cue(pres, new_slide("section_divider", group_label), group_label)]
    for i, lines in enumerate(slides, 1):
        cue_uuids.append(add_cue(pres, new_slide("liturgy", group_label, lines), f"{group_label} {i}"))
    _group(pres, group_label, cue_uuids)


def fill_sending(pres: presentation_pb2.Presentation) -> None:
    """파송의 노래 — the divider, the two operator cue cards, then the fixed closing song.

    The same song closes every service, so it comes from ``content.SENDING_SONG`` rather than
    ``ServiceData``, and it is sung twice (once before 축도, once before 주기도문) — which is what
    the two cards announce. Those two are **keyed labels**, not full-screen cards: Keynote gives
    them a keyed label and no navy plate, the same test that picks ``content.KEYED_SECTIONS``
    (#234). The 파송의 노래 divider itself keeps its plate.
    """
    label = content.DIVIDER_LABELS["sending"]
    cue_uuids = [
        add_cue(
            pres,
            new_slide("section_divider", label, content.SENDING_SONG["title"]),
            label,
        )
    ]
    for cue in content.SENDING_CUES:
        cue_uuids.extend(_keyed_cues(pres, cue))
    _group(pres, label, cue_uuids)
    fill_song(pres, content.SENDING_SONG)


def fill_sermon_extra(
    pres: presentation_pb2.Presentation, refs: list[str], passages: list[list[dict]]
) -> None:
    """Extra sermon verse slides typed in review (#114). Analog of ``fill_sermon_extra_slides``.

    One group per reference, named after it — no divider, since the reference is already the
    group's name and every slide carries the citation label. An empty passage (the lookup
    failed at save) is skipped; the operator adds it by hand, as with Keynote.
    """
    for ref, passage in zip(refs, passages):
        if not passage:
            continue
        _group(pres, ref, _verse_cues(pres, ref, [Verse(**v) for v in passage]))


# ── Protobuf primitives (pure protobuf; analog of the AppleScript primitives) ──

def new_presentation(name: str) -> presentation_pb2.Presentation:
    """A fresh, empty ``Presentation`` with a new UUID and ``name`` (the service date).

    Sets the same document-level fields ProPresenter itself writes: application info,
    the chord-chart platform tag, and the empty-but-present ``background`` / ``ccli``
    sub-messages. Note there is no document-level canvas size — that lives per slide.
    """
    pres = presentation_pb2.Presentation()
    pres.uuid.string = elements.new_uuid()
    pres.name = name
    pres.application_info.platform = pres.application_info.PLATFORM_MACOS
    pres.application_info.application = pres.application_info.APPLICATION_PROPRESENTER
    pres.application_info.application_version.major_version = PP_VERSION[0]
    pres.application_info.application_version.minor_version = PP_VERSION[1]
    pres.chord_chart.platform = url_pb2.URL.PLATFORM_MACOS
    pres.background.SetInParent()
    pres.ccli.SetInParent()
    return pres


def new_slide(style_key: str, *args, **kwargs) -> slide_pb2.Slide:
    """Build a styled slide for ``style_key`` (see ``styles.STYLE_KEYS``) from the content in
    ``args``/``kwargs`` — e.g. ``new_slide("liturgy", "사도신경", lines)``.

    Replaces #171's ``clone_slide``: with no authored style-kit deck (#170), the look is
    composed from ``styles.py`` rather than deep-copied from a prototype.
    """
    try:
        builder = styles.BUILDERS[style_key]
    except KeyError:
        raise KeyError(f"unknown style key {style_key!r}; expected one of {styles.STYLE_KEYS}") from None
    return builder(*args, **kwargs)


def add_cue(
    pres: presentation_pb2.Presentation,
    slide: slide_pb2.Slide,
    name: str = "",
    label_color: tuple[int, int, int] | None = None,
    note: str = "",
) -> uuid_pb2.UUID:
    """Wrap ``slide`` in a ``Cue`` (via ``Action`` -> ``PresentationSlide``), append it to
    ``pres.cues``, and return the cue's UUID (for the owning group's ``cue_identifiers``).

    Passing ``label_color`` also writes ``Action.Label`` — ProPresenter's per-slide **label**,
    the colored caption on the slide in the grid. That is a different field from ``Cue.name``,
    which PP does *not* surface there: the HTTP API reports a named-but-unlabeled cue as
    ``{"label": ""}``. It is how a song's V1/C/B structure stays readable without promoting each
    section to its own group (see design doc Decision 4).

    ``note`` writes ProPresenter's per-slide **notes** pane (``PresentationSlide.Notes``) — the
    booth-facing text the operator reads but the congregation never sees, e.g. the 성가대 lighting
    cue the Keynote deck kept as a presenter note.
    """
    cue = pres.cues.add()
    cue.uuid.string = elements.new_uuid()
    cue.name = name
    cue.completion_action_type = cue_pb2.Cue.COMPLETION_ACTION_TYPE_LAST
    cue.isEnabled = True

    action = cue.actions.add()
    action.uuid.string = elements.new_uuid()
    action.name = name
    action.isEnabled = True
    # Mandatory: without the explicit type ProPresenter doesn't route the action to the slide.
    action.type = action_pb2.Action.ACTION_TYPE_PRESENTATION_SLIDE
    if label_color is not None and name:
        action.label.text = name
        elements.set_color(action.label.color, label_color)
    presentation_slide = action.slide.presentation
    presentation_slide.chord_chart.platform = url_pb2.URL.PLATFORM_MACOS
    presentation_slide.base_slide.CopyFrom(slide)
    if note:
        presentation_slide.notes.rtf_data = rtf.plain(note, styles.NOTE)
    return cue.uuid


def add_group(
    pres: presentation_pb2.Presentation,
    label: str,
    color: tuple[int, int, int] | None,
    cue_uuids: list[uuid_pb2.UUID],
) -> uuid_pb2.UUID:
    """Append a ``CueGroup`` (``Group`` label+color + ``cue_identifiers``) and return its group UUID."""
    cue_group = pres.cue_groups.add()
    group = cue_group.group
    group.uuid.string = elements.new_uuid()
    group.name = label
    if color is not None:
        elements.set_color(group.color, color)
    for cue_uuid in cue_uuids:
        cue_group.cue_identifiers.add().string = cue_uuid.string
    return group.uuid


def add_arrangement(
    pres: presentation_pb2.Presentation, name: str, group_uuids: list[uuid_pb2.UUID]
) -> uuid_pb2.UUID:
    """Append a ``Presentation.Arrangement`` sequencing ``group_uuids`` in play order.

    Arrangements reference *group* UUIDs (not cue UUIDs), and the first one added becomes the
    selected one. **Unused by the generator**: #176 built song repeats on this and rejected the
    result (flat group bars, no nesting — design doc Decision 4), so no deck writes
    ``arrangements`` or ``selected_arrangement``. Kept as a #172 primitive, and note that a
    selected arrangement is document-level and singular — any group missing from it stops
    playing at all.
    """
    arrangement = pres.arrangements.add()
    arrangement.uuid.string = elements.new_uuid()
    arrangement.name = name
    for group_uuid in group_uuids:
        arrangement.group_identifiers.add().string = group_uuid.string
    if not pres.selected_arrangement.string:
        pres.selected_arrangement.string = arrangement.uuid.string
    return arrangement.uuid


def place_image(slide: slide_pb2.Slide, image_path: str) -> None:
    """Add a full-bleed media element to ``slide`` (hymn PNG pages, band lead sheets) (#179)."""
    elements.image(slide, (0.0, 0.0, *styles.CANVAS), image_path)


# NOTE: there is deliberately no Glossa fill either, though #177 originally scoped one.
# Glossa (live KO→EN translation) is a ProPresenter **Prop**, not a slide. Props are their own
# layer (`Action.ClearType.CLEAR_TARGET_LAYER_PROP`), so the translation composites over whatever
# is on screen — green lyric slides, navy verse plates, announcements alike — and the operator
# shows/hides it whenever a moment calls for it, instead of at cue boundaries the generator
# guessed at in advance. A web element on its own cue *replaces* the slide under it, which would
# force a choice between showing a verse plate and showing the translation.
#
# It also cannot be shipped in the weekly file: `Presentation` has no props field, and props live
# in the machine-local `~/Documents/ProPresenter/Configuration/Props` store. A cue can only
# *reference* one (`Action.PropType.identification` -> `CollectionElementType`), i.e. a UUID from
# one machine's library — the same non-portability that sank group presets in #176. So the prop is
# a one-time setup on the church Mac mini, and the generator writes nothing for it.
#
# DECIDED (#177, 2026-08-26). Do not add a `fill_glossa`, a `styles.glossa` slide, or a
# `GLOSSA_URL` env var — all three were built and removed. See the design doc, "Glossa is a Prop".

# NOTE: there is deliberately no `set_transition` primitive, though #172 listed one.
# ProPresenter 21.4 *drops every slide that carries a `PresentationSlide.transition`* unless
# the transition references a real built-in Effect — the slide silently vanishes from the
# document (its group reports zero slides and its thumbnail 404s), and a deck-level
# `Presentation.transition` makes the whole document unreadable to the app. The Effect
# identity is an opaque `render_id` that no deck on disk and no string in the app bundle
# reveals, so it cannot be synthesized.
#
# DECIDED (#174, closed 2026-08-24): worship runs the *global* cut transition set in the
# ProPresenter UI, which every generated deck inherits because it carries no transition of
# its own. Do not add a transition primitive, a per-deck default, or a `Transition` field —
# there is nothing to gain and a silently destroyed deck to lose.


def serialize(pres: presentation_pb2.Presentation, out_pro: str) -> str:
    """Write ``pres`` to ``out_pro`` (a ``.pro`` is one raw-serialized message). Returns the path."""
    Path(out_pro).write_bytes(pres.SerializeToString())
    return out_pro


def load(pro_path: str) -> presentation_pb2.Presentation:
    """Parse an existing ``.pro`` — the inverse of ``serialize`` (used by the round-trip tests)."""
    pres = presentation_pb2.Presentation()
    pres.ParseFromString(Path(pro_path).read_bytes())
    return pres
