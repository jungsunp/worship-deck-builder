"""Ground-up ProPresenter ``.pro`` generator (v3 migration, epic #184).

**Skeleton only (#171).** This module defines the generator's *shape* — the entry
point, the per-section ``fill_*`` decomposition (mirroring ``keynote/build.py``),
and the protobuf primitives — but every body raises ``NotImplementedError``. The
real serialization is #172; per-section content details land in #175–#179. See
``docs/propresenter-generator-design.md`` for the design rationale.

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
a slide (``PresentationSlide`` carries no theme field); font/color/size live on each
text element. So the look comes from *cloning* styled exemplar slides authored once
in ProPresenter (#170) — see ``style_kit.py`` — and swapping only the text runs
(``rtf.py``). Section-specific looks are just different prototypes.

Output: one weekly ``.pro`` the operator imports and clicks through — the direct
analog of today's single ``.key``. Service sections become ProPresenter *groups*.
"""

from __future__ import annotations

# Import order is load-bearing here; sorting it moves `pb` below the *_pb2 imports that
# depend on its side effect, and the module then fails to import.
# isort: off
from . import pb  # noqa: F401 -- side effect: puts pb/ on sys.path for the bare *_pb2 imports

import presentation_pb2
import slide_pb2
import uuid_pb2

# isort: on
from worship_deck.parse import ServiceData

# Service order, top to bottom — the fixed liturgy sequence build() walks. Weekly groups draw
# from ServiceData; the fixed-wording groups (사도신경 creed, 주기도문 prayer, dividers) come from
# content.py. This replaces anchors.py's landmark detection with a plain declared order.
# (Documented here for the reader; the real build() wires these to the fill_* calls in #172.)


# ── Entry point ───────────────────────────────────────────────────────────────

def build(data: ServiceData, out_pro: str) -> tuple[str, dict[str, float]]:
    """Serialize ``data`` into a single weekly ``.pro`` at ``out_pro``.

    Mirrors ``keynote.build.build(data, template, out)`` but ground-up: create a
    fresh ``Presentation`` (``new_presentation``), then walk the service order
    calling each ``fill_*`` — each appends its cues + one ``CueGroup`` — and finally
    ``serialize`` the whole message. Returns ``(out_pro, steps)`` where ``steps`` is
    per-section timing (like the Keynote builder), for ``obs.run_record``.

    #172 implements the body.
    """
    raise NotImplementedError("#172: ground-up ServiceData -> Presentation serialization")


# ── Per-section fillers (mirror keynote/build.py fill_*) ──────────────────────
# Each appends its slide cues to ``pres.cues`` and one ``CueGroup`` (label + color) to
# ``pres.cue_groups``, referencing the cues by UUID. No return-count bookkeeping is needed
# (unlike Keynote): nothing downstream shifts.

def fill_date(pres: presentation_pb2.Presentation, date: str, sermon_title: str) -> None:
    """Intro + ending date/sermon-title slides. Analog of ``set_date_slides``."""
    raise NotImplementedError("#172")


def fill_worship_songs(pres: presentation_pb2.Presentation, songs: list[dict]) -> None:
    """찬양 medley — one title + lyric group per song. Delegates to ``fill_song`` per song."""
    raise NotImplementedError("#172 / lyric re-chunk #175 / arrangement #176")


def fill_song(pres: presentation_pb2.Presentation, song: dict) -> None:
    """One song: a title slide + ≤2-line lyric slides. Shared by worship + confession.

    When ``song['sections']`` is populated (operator-labeled V1/C/B, #113), each becomes
    its own ``CueGroup`` and ``song['arrangement']`` drives an ``Arrangement`` (#176);
    otherwise the flat ``song['lines']`` are chunked into one group (#175).
    """
    raise NotImplementedError("#172 / #175 / #176")


def fill_confession(pres: presentation_pb2.Presentation, song: dict) -> None:
    """고백의 찬양 — divider + title + lyric slides. Delegates to ``fill_song``."""
    raise NotImplementedError("#172")


def fill_choir(pres: presentation_pb2.Presentation, song: dict) -> None:
    """성가대 — title (with composer credit) + lyric slides."""
    raise NotImplementedError("#172")


def fill_verse_slides(
    pres: presentation_pb2.Presentation, group_label: str, verses: list[dict]
) -> None:
    """Bilingual scripture (예배의 부름 / 말씀 bodies) — 개역한글 + ESV per verse. Full-screen."""
    raise NotImplementedError("#172 / #178")


def fill_announcements(pres: presentation_pb2.Presentation, items: list[str]) -> None:
    """교회소식 — one full-screen slide per item (gold title + white detail)."""
    raise NotImplementedError("#172 / #178")


def fill_offering_hymn(
    pres: presentation_pb2.Presentation, number: str, title: str, image_paths: list[str]
) -> None:
    """봉헌 — native-text title slide + the downloaded hymn PNG pages placed as images."""
    raise NotImplementedError("#172 / #179")


def fill_liturgy(pres: presentation_pb2.Presentation, group_label: str, paragraphs: list[str]) -> None:
    """Fixed-wording liturgy (사도신경 creed, 주기도문 Lord's Prayer) from ``content.py`` constants."""
    raise NotImplementedError("#172 / #178")


def fill_sermon_extra(
    pres: presentation_pb2.Presentation, refs: list[str], passages: list[list[dict]]
) -> None:
    """Extra sermon verse slides typed in review (#114). Analog of ``fill_sermon_extra_slides``."""
    raise NotImplementedError("#172 / #178")


# ── Protobuf primitives (pure protobuf; analog of the AppleScript primitives) ──

def new_presentation(name: str) -> presentation_pb2.Presentation:
    """A fresh, empty ``Presentation`` with a new UUID and ``name`` (the service date)."""
    raise NotImplementedError("#172")


def clone_slide(style_key: str) -> slide_pb2.Slide:
    """Deep-copy the style-kit prototype for ``style_key`` (see ``style_kit.py``), assigning
    fresh element UUIDs. The clone carries the baked look; callers swap only its text (``rtf``)."""
    raise NotImplementedError("#172")


def add_cue(pres: presentation_pb2.Presentation, slide: slide_pb2.Slide, name: str) -> uuid_pb2.UUID:
    """Wrap ``slide`` in a ``Cue`` (via ``Action`` -> ``PresentationSlide``), append it to
    ``pres.cues``, and return the cue's UUID (for the owning group's ``cue_identifiers``)."""
    raise NotImplementedError("#172")


def add_group(
    pres: presentation_pb2.Presentation, label: str, color, cue_uuids: list[uuid_pb2.UUID]
) -> uuid_pb2.UUID:
    """Append a ``CueGroup`` (``Group`` label+color + ``cue_identifiers``) and return its group UUID."""
    raise NotImplementedError("#172")


def add_arrangement(
    pres: presentation_pb2.Presentation, name: str, group_uuids: list[uuid_pb2.UUID]
) -> None:
    """Append a ``Presentation.Arrangement`` sequencing ``group_uuids`` in play order (#176)."""
    raise NotImplementedError("#176")


def place_image(slide: slide_pb2.Slide, image_path: str) -> None:
    """Add a full-bleed media element to ``slide`` (hymn PNG pages, band lead sheets) (#179)."""
    raise NotImplementedError("#172 / #179")


def serialize(pres: presentation_pb2.Presentation, out_pro: str) -> str:
    """Write ``pres`` to ``out_pro`` (``write_bytes(pres.SerializeToString())``). Returns the path."""
    raise NotImplementedError("#172")
