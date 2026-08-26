"""Ground-up ProPresenter ``.pro`` generator (v3 migration, epic #184).

**The protobuf primitives are implemented (#172), and the sung-lyric fillers with
them (#175: ``fill_worship_songs`` / ``fill_song`` / ``fill_confession``).** The
remaining ``fill_*`` bodies land with their content details in #178–#179, as does
``build()`` itself. See ``docs/propresenter-generator-design.md`` for the design
rationale and the decoded ``.pro`` anatomy these primitives are built from.

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
from worship_deck.lyrics import linebreak
from worship_deck.lyrics.transcribe import Song, arranged_chunks
from worship_deck.parse import ServiceData

from . import content, elements, styles

# The dev/church ProPresenter build the vendored protos are pinned to (#191 re-pins to 18.4).
PP_VERSION = (21, 4)

# Service order, top to bottom — the fixed liturgy sequence build() walks. Weekly groups draw
# from ServiceData; the fixed-wording groups (사도신경 creed, 주기도문 prayer, dividers) come from
# content.py. This replaces anchors.py's landmark detection with a plain declared order.
# (Documented here for the reader; build() wires these to the fill_* calls in #180.)


# ── Entry point ───────────────────────────────────────────────────────────────

def build(data: ServiceData, out_pro: str) -> tuple[str, dict[str, float]]:
    """Serialize ``data`` into a single weekly ``.pro`` at ``out_pro``.

    Mirrors ``keynote.build.build(data, template, out)`` but ground-up: create a
    fresh ``Presentation`` (``new_presentation``), then walk the service order
    calling each ``fill_*`` — each appends its cues + one ``CueGroup`` — and finally
    ``serialize`` the whole message. Returns ``(out_pro, steps)`` where ``steps`` is
    per-section timing (like the Keynote builder), for ``obs.run_record``.

    The primitives below are done (#172); this body waits on the fill_* content work.
    """
    raise NotImplementedError("#180: walk the service order once the fill_* bodies land")


# ── Per-section fillers (mirror keynote/build.py fill_*) ──────────────────────
# Each appends its slide cues to ``pres.cues`` and one ``CueGroup`` (label + color) to
# ``pres.cue_groups``, referencing the cues by UUID. No return-count bookkeeping is needed
# (unlike Keynote): nothing downstream shifts.

def fill_date(pres: presentation_pb2.Presentation, date: str, sermon_title: str) -> None:
    """Intro + ending date/sermon-title slides. Analog of ``set_date_slides``."""
    raise NotImplementedError("#178")


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
    cue_uuids = [add_cue(pres, new_slide("song_banner", parsed.title), parsed.title)]
    for label, lines in _chunks(parsed):
        cue_uuids.append(
            add_cue(pres, new_slide("worship_lyric_ko", lines), label, styles.section_color(label))
        )
    cue_uuids.append(add_cue(pres, new_slide("blank_green"), ""))
    add_group(pres, parsed.title, color or styles.GROUP_COLORS["찬양"], cue_uuids)


def fill_confession(pres: presentation_pb2.Presentation, song: dict) -> None:
    """고백의 찬양 — full-screen divider + blank, then the song's banner + lyrics (#175).

    Mirrors ``keynote.build.fill_confession_slides``: the divider carries the section heading
    over the week's bracketed song title, and the rest of the section is exactly a worship-song
    unit, so it delegates to ``fill_song``. Two groups result: the section divider, then the
    song under its own title.
    """
    label = content.DIVIDER_LABELS["confession_song"]
    color = styles.GROUP_COLORS[label]
    parsed = Song(**song)
    cue_uuids = [
        add_cue(pres, new_slide("section_divider", label, f"[ {parsed.title} ]"), label),
        add_cue(pres, new_slide("blank_green"), ""),
    ]
    add_group(pres, label, color, cue_uuids)
    fill_song(pres, song)


def fill_choir(pres: presentation_pb2.Presentation, song: dict) -> None:
    """성가대 — title (with composer credit) + lyric slides."""
    raise NotImplementedError("#178")


def fill_verse_slides(
    pres: presentation_pb2.Presentation, group_label: str, verses: list[dict]
) -> None:
    """Bilingual scripture (예배의 부름 / 말씀 bodies) — 개역한글 + ESV per verse. Full-screen."""
    raise NotImplementedError("#178")


def fill_announcements(pres: presentation_pb2.Presentation, items: list[str]) -> None:
    """교회소식 — one full-screen slide per item (gold title + white detail)."""
    raise NotImplementedError("#178")


def fill_offering_hymn(
    pres: presentation_pb2.Presentation, number: str, title: str, image_paths: list[str]
) -> None:
    """봉헌 — native-text title slide + the downloaded hymn PNG pages placed as images."""
    raise NotImplementedError("#179")


def fill_liturgy(pres: presentation_pb2.Presentation, group_label: str, paragraphs: list[str]) -> None:
    """Fixed-wording liturgy (사도신경 creed, 주기도문 Lord's Prayer) from ``content.py`` constants."""
    raise NotImplementedError("#178")


def fill_sermon_extra(
    pres: presentation_pb2.Presentation, refs: list[str], passages: list[list[dict]]
) -> None:
    """Extra sermon verse slides typed in review (#114). Analog of ``fill_sermon_extra_slides``."""
    raise NotImplementedError("#178")


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
) -> uuid_pb2.UUID:
    """Wrap ``slide`` in a ``Cue`` (via ``Action`` -> ``PresentationSlide``), append it to
    ``pres.cues``, and return the cue's UUID (for the owning group's ``cue_identifiers``).

    Passing ``label_color`` also writes ``Action.Label`` — ProPresenter's per-slide **label**,
    the colored caption on the slide in the grid. That is a different field from ``Cue.name``,
    which PP does *not* surface there: the HTTP API reports a named-but-unlabeled cue as
    ``{"label": ""}``. It is how a song's V1/C/B structure stays readable without promoting each
    section to its own group (see design doc Decision 4).
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
