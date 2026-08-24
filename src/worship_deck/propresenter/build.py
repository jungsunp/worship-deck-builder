"""Ground-up ProPresenter ``.pro`` generator (v3 migration, epic #184).

**The protobuf primitives are implemented (#172); the per-section ``fill_*`` bodies
are not** — those land with their content details in #175–#179, as does ``build()``
itself. See ``docs/propresenter-generator-design.md`` for the design rationale and
the decoded ``.pro`` anatomy these primitives are built from.

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
from worship_deck.parse import ServiceData

from . import elements, styles

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


def fill_worship_songs(pres: presentation_pb2.Presentation, songs: list[dict]) -> None:
    """찬양 medley — one title + lyric group per song. Delegates to ``fill_song`` per song."""
    raise NotImplementedError("lyric re-chunk #175 / arrangement #176")


def fill_song(pres: presentation_pb2.Presentation, song: dict) -> None:
    """One song: a title slide + ≤2-line lyric slides. Shared by worship + confession.

    When ``song['sections']`` is populated (operator-labeled V1/C/B, #113), each becomes
    its own ``CueGroup`` and ``song['arrangement']`` drives an ``Arrangement`` (#176);
    otherwise the flat ``song['lines']`` are chunked into one group (#175).
    """
    raise NotImplementedError("#175 / #176")


def fill_confession(pres: presentation_pb2.Presentation, song: dict) -> None:
    """고백의 찬양 — divider + title + lyric slides. Delegates to ``fill_song``."""
    raise NotImplementedError("#175")


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
    pres: presentation_pb2.Presentation, slide: slide_pb2.Slide, name: str = ""
) -> uuid_pb2.UUID:
    """Wrap ``slide`` in a ``Cue`` (via ``Action`` -> ``PresentationSlide``), append it to
    ``pres.cues``, and return the cue's UUID (for the owning group's ``cue_identifiers``)."""
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
    """Append a ``Presentation.Arrangement`` sequencing ``group_uuids`` in play order (#176).

    Arrangements reference *group* UUIDs (not cue UUIDs) — a song's V1/C/B groups replayed in
    the operator-labeled order. The first arrangement added becomes the selected one.
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


# NOTE: there is deliberately no `set_transition` primitive, though #172 listed one.
# ProPresenter 21.4 *drops every slide that carries a `PresentationSlide.transition`* unless
# the transition references a real built-in Effect — the slide silently vanishes from the
# document (its group reports zero slides and its thumbnail 404s), and a deck-level
# `Presentation.transition` makes the whole document unreadable to the app. The Effect
# identity is an opaque `render_id` that no deck on disk and no string in the app bundle
# reveals, so #174 has to capture it by decoding a hand-authored slide first.


def serialize(pres: presentation_pb2.Presentation, out_pro: str) -> str:
    """Write ``pres`` to ``out_pro`` (a ``.pro`` is one raw-serialized message). Returns the path."""
    Path(out_pro).write_bytes(pres.SerializeToString())
    return out_pro


def load(pro_path: str) -> presentation_pb2.Presentation:
    """Parse an existing ``.pro`` — the inverse of ``serialize`` (used by the round-trip tests)."""
    pres = presentation_pb2.Presentation()
    pres.ParseFromString(Path(pro_path).read_bytes())
    return pres
