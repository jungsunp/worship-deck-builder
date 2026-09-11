"""Baked slide styling for generated ``.pro`` decks (v3 migration, #172).

ProPresenter has **no runtime theme reference**: ``PresentationSlide`` carries no theme
field and ``Action.SlideType`` has ``reserved "template"``, so font/color/size live on each
element. #170 closed on the consequence — there is no authored style-kit ``.pro`` to clone
from; the generator bakes the look per slide from the values here.

Those values are the interim pick recorded on #168: lyric **Option A (검정 스트립)** and
full-screen **Option 3 (네이비 프레임)**. ``scripts/render_style_samples.py`` holds the same
numbers as HTML/CSS and ``docs/style-samples/*.png`` is the rendering to match — except the
Option A strip metrics (``LYRIC_STRIP_PAD``, ``LYRIC_KO`` tracking/line spacing), which were
re-tuned in #175 against ``docs/style-references/ref-hillsong.png`` on real ProPresenter
renders: the sample CSS left the strips loose around the text and touching each other. Restyling is a
code edit here, not a runtime setting (#222/#223 were closed on that point) — which is exactly
why these are plain module constants rather than a binary. The finalization meeting decides
from the #241 sample sheet and #243 re-bakes these values.

Each ``STYLE_KEYS`` entry has a builder below returning a finished ``Slide``; the per-section
``build.fill_*`` functions (#175–#179) call them with weekly content.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

# isort: off
from . import pb  # noqa: F401 -- side effect: puts pb/ on sys.path for the bare *_pb2 imports

import slide_pb2

# isort: on
from worship_deck.bible import layout

from . import announce, content, rtf
from . import elements as el

# The slide types the generator can produce. Each maps to one builder function below.
STYLE_KEYS = (
    "worship_lyric_ko",         # sung lyrics, lower-third, up to 2 Korean lines
    "worship_lyric_bilingual",  # 1 dominant KO line + 1 smaller EN line (needs a KO+EN source, #228)
    "song_banner",              # keyed lower-third song title (worship medley)
    "verse_fullscreen",         # bilingual scripture body (개역한글 + ESV)
    "announcement",             # 교회 소식 notice (title + 날짜/장소/문의 라벨 레일)
    "section_divider",          # section heading (예배의 부름 / 봉헌 / 교회 소식 …)
    "verse_divider",            # the 말씀 reference plate — the divider at reference scale (#250)
    "sermon_title",             # the week's sermon title — the divider at sentence scale (#250)
    "keyed_label",              # section heading keyed over the live camera (#234)
    "liturgy",                  # fixed-wording full-screen (사도신경 recitation / 주기도문)
    "liturgy_responsive",       # 사도신경 문답 — gold question, rule, white answer (#244)
    "service_intro",            # N부 예배를 시작합니다 + sermon title / ref / date
    "service_outro",            # N부 예배를 마칩니다 + date
    "text_card",                # centered fixed-wording card (표어 / 환영)
    "closing_note",             # 폐회 안내 — instruction over a rule, farewell under it (#249)
    "logo_plate",               # the church logo alone, centered — the deck's last plate (#249)
    "blank_green",              # blank chroma-green separator
    "image",                    # full-bleed image slide (hymn PNG pages, band lead sheets)
)

CANVAS = (1920.0, 1080.0)

# ── Church artwork ────────────────────────────────────────────────────────────
# Lifted from the church's own deck (extracted from master.key's media) and normalised to the
# canvas: the deck is generated from scratch, so anything that rode along inside the template
# has to ship with the generator. Committed because they are public church branding — no member
# names, no offering amounts (unlike anything under data/).
ASSET_DIR = Path(__file__).parent / "assets"
LOGO = str(ASSET_DIR / "npc-logo.png")  # 노스필드장로교회, white-on-transparent (master slides 1–3)
# The two full-bleed pre-service plates the deck opens with (master slides 4–5): the building at
# sunrise, then the 환영합니다 graphic. The welcome graphic carries the year's 표어 ("가족"), so
# replace it each January alongside ``content.WELCOME_CARD``.
PRE_SERVICE_IMAGES = (
    str(ASSET_DIR / "pre-service-church.jpg"),
    str(ASSET_DIR / "pre-service-welcome.jpg"),
)
# The purple watercolour stroke Keynote keys its section labels over (master slides 61–63, #234),
# cropped from master.key's `pngwing.com 12` to its opaque box so the placement rects below can be
# the plain numbers measured off the deck. A stock paint texture, in weekly production use in the
# church's own deck; no member data, same bar as the artwork above.
BRUSH = str(ASSET_DIR / "brush-stroke-purple.png")
BRUSH_ASPECT = 1119 / 251
# The keyed-label plate (#234). Drawn by `scripts/make_keyed_art.py` rather than sourced, so the
# palette is exactly the deck's and there is no licence question; hard edges also key more cleanly
# than a soft-alpha stroke (#192). All are drawn at BRUSH_ASPECT, so they share the measured rects.


@dataclass(frozen=True)
class Plate:
    """One keyed-label plate: the artwork and the two numbers its silhouette dictates.

    ``inset`` is the fraction of the container width kept clear of text at each end. It belongs to
    the plate rather than to the section because the silhouette decides it — a rounded end eats
    more of its own box than a square-cut one, so the pill needs more clearance than the skewed bar.
    """

    image: str
    aspect: float = BRUSH_ASPECT
    inset: float = 0.10


# **Neither of these ships any more** — the plate is drawn now (#247, see below). They are kept as
# the #241 review's comparison material: `M1` is what #234's bake-off picked and the deck carried
# until 2026-09-05 (a skewed bar with a NAVY→DEEP ramp and a gold rule, chosen over every flat,
# gradient, scrim and repainted-stroke treatment), and `A` is Keynote's own watercolour. #247's own
# candidates — a backdrop-material fill and three simulated-glass treatments of it — were rejected
# on review and their bakes deleted; `scripts/make_keyed_art.py` still draws M1.
KEYED_ART: dict[str, Plate] = {
    "M1": Plate(str(ASSET_DIR / "m1-angled-bar.png")),
    "A": Plate(BRUSH),
}
# The blurred backdrop behind every full-screen slide (#224). Pre-blurred by
# `scripts/make_backdrop.py` because ProPresenter cannot blur one itself — see `_framed` below.


@dataclass(frozen=True)
class Backdrop:
    """A backdrop image and the navy tint that belongs over it — one look, not two settings.

    The blur and brightness are baked into ``image``; the tint cannot be, because ``_framed``
    draws it as a live shape and baking it would tint twice. Pairing them here keeps that split
    from becoming a trap: tint is the strongest of the three, so a backdrop swapped without its
    tint is a different look than the one that was picked. ``scripts/make_backdrop.py``'s
    ``STRENGTHS`` table owns the numbers, and a test pins the two files together.
    """

    image: str
    tint: float


# Three curated sources, baked at the shipped strength. The script re-renders the other strengths
# for #241's sample sheet; #225 picks the final look and #243 applies it — by then a one-line swap.
BACKDROP_DIR = ASSET_DIR / "backdrops"
BACKDROP_STRENGTH = "gentle"  # must match make_backdrop.SHIPPED
BACKDROPS: dict[str, Backdrop] = {
    # the church building at golden hour
    "church": Backdrop(str(BACKDROP_DIR / f"church-exterior-{BACKDROP_STRENGTH}.png"), 0.56),
    # the 2025-11 all-church-members photo
    "congregation": Backdrop(str(BACKDROP_DIR / f"congregation-{BACKDROP_STRENGTH}.png"), 0.56),
    # CC0 dark church interior
    "sanctuary": Backdrop(str(BACKDROP_DIR / f"sanctuary-cc0-{BACKDROP_STRENGTH}.png"), 0.56),
}
BACKDROP = BACKDROPS["church"]

# ── Palette (Option 3 네이비 프레임) ────────────────────────────────────────────
# RGB triples; RTF has no alpha, so the sample's translucent inks are pre-blended over the
# navy ground. Element fills (which *do* have alpha) keep their alpha as the 4th component.
NAVY = (0x10, 0x20, 0x3B)
ACCENT = (0xFF, 0xD4, 0x47)  # gold: verse numbers, rules, labels
INK = (0xFF, 0xFF, 0xFF)
MUTED = (0xBC, 0xC0, 0xC7)  # white .72 over navy — ESV body, announcement detail
BLACK = (0x00, 0x00, 0x00)  # Option A lyric strips
# The church's exact key green, read off the current Keynote lyric slides (#192): reusing it
# guarantees the ATEM upstream keyer treats a generated lyric slide exactly like today's.
# It backs every sung-lyric slide, not just blank_green() — an unbacked slide renders black.
CHROMA_GREEN = (0x81, 0xD6, 0x54)

TINT_RGBA = (*NAVY, BACKDROP.tint)  # the live half of the BACKDROP look (#224)


@contextmanager
def use_backdrop(backdrop: Backdrop):
    """Build slides against a *different* backdrop for the length of the block. Dev scripts only.

    ``_framed`` reads the module constants, so a deck can otherwise carry exactly one strength —
    which makes a side-by-side comparison of two impossible. ``scripts/make_pro_demo.py`` uses this
    to emit one group per candidate strength; nothing in the pipeline calls it.

    This is **not** #222 returning. There is no runtime style layer, no config surface and no
    persistence: it swaps two module constants so a comparison deck can be built, and #241's theme
    sets are the real answer if more than the backdrop ever needs to vary per deck.
    """
    global BACKDROP, TINT_RGBA
    previous = BACKDROP, TINT_RGBA
    BACKDROP, TINT_RGBA = backdrop, (*NAVY, backdrop.tint)
    try:
        yield backdrop
    finally:
        BACKDROP, TINT_RGBA = previous


@contextmanager
def use_font(family: str, regular: str, bold: str,
             ko_char_w: float, en_char_w: float, pitch: float):
    """Set the whole deck in a different Korean face for the length of the block. Dev scripts only.

    Same shape and same reason as ``use_backdrop``: every ``Style`` below is frozen and was built
    at import with this module's font names baked in, so one process can otherwise emit exactly one
    face — which makes a side-by-side deck impossible. ``scripts/make_pro_demo.py --font`` uses it;
    nothing in the pipeline does. Shipping a face is a six-constant edit here, not this.

    The measurements are not cosmetic and have to travel with the face:

    ``ko_char_w`` sets ``CHAR_W_KO``, which decides how many verses fit on a scripture cue, where a
    lyric line breaks and whether a 교회 소식 notice needs a second plate.

    ``en_char_w`` sets ``CHAR_W_EN`` separately, because a Korean face's Latin is drawn to its own
    width — the 교회 소식 rail rows are dates, amounts and email addresses, and those are the boxes
    that overflowed when only the Hangul number moved.

    ``pitch`` sets ``LINE_PITCH``. The candidate faces measure 1.14 to 1.50 against Apple SD Gothic
    Neo's 1.20, and a face 4% taller overflows every tight box in the deck by a point.

    ``scripts/measure_advance.swift`` prints all three for an installed face; scale them onto the
    deck's constants rather than substituting — see the table in ``scripts/make_pro_demo.py``.
    """
    global FONT_FAMILY, FONT_REGULAR, FONT_BOLD
    global CHAR_W_KO, CHAR_W_EN, LINE_PITCH
    global LITURGY_HEADER_H  # the one module constant baked from the pitch at import
    scale = {name: value for name, value in globals().items() if isinstance(value, Style)}
    previous = (FONT_FAMILY, FONT_REGULAR, FONT_BOLD,
                CHAR_W_KO, CHAR_W_EN, LINE_PITCH, LITURGY_HEADER_H)
    for name, style in scale.items():  # before FONT_BOLD is rebound out from under the test
        globals()[name] = replace(style, family=family,
                                  font=bold if style.font == FONT_BOLD else regular)
    FONT_FAMILY, FONT_REGULAR, FONT_BOLD = family, regular, bold
    CHAR_W_KO = ko_char_w
    CHAR_W_EN, LINE_PITCH = en_char_w, pitch
    LITURGY_HEADER_H = line_height(LITURGY_TITLE.size) + LITURGY_TITLE_GAP
    try:
        yield
    finally:
        globals().update(scale)
        (FONT_FAMILY, FONT_REGULAR, FONT_BOLD,
         CHAR_W_KO, CHAR_W_EN, LINE_PITCH, LITURGY_HEADER_H) = previous


FRAME_FILL_RGBA = (0x0A, 0x14, 0x28, 0.35)
FRAME_STROKE_RGBA = (*INK, 0.32)
FRAME_STROKE_WIDTH = 1.5
FRAME_RADIUS = 0.01  # ProPresenter roundness is a fraction of the shorter side (~10px)

# Fonts. The deck was set in Apple SD Gothic Neo — the safe default, since it ships with macOS —
# until the operator reviewed the keyed plate and objected that it "doesn't really mix well with
# round boxes" (#247). It doesn't: its terminals are squared and its `ㅇ` flattened, which fights
# the deck's 10pt rounded furniture. NanumSquare Round won a five-face bake-off run as full weekly
# decks (SUIT second, both kept in `scripts/make_pro_demo.py` for the #241 review). SIL OFL.
#
# **This face must be installed on the church mini** — done on mini #1 on 2026-09-09 (#191; README
# "Presentation machine"). ProPresenter substitutes silently for a font it cannot find, so a
# missing face looks like a style bug, not an error.
FONT_FAMILY = "NanumSquareRound"
FONT_BOLD = "NanumSquareRoundB"
FONT_REGULAR = "NanumSquareRoundR"

# The face's own CoreText metrics, which every box in this module is measured against. They live
# here rather than in `bible.layout` because `master.key` is *not* set in this face: the Keynote
# builder keeps layout's defaults, and only the .pro path passes these in.
#
# Hangul and the pitch are layout's estimates **scaled** by NanumSquare Round's measurements over
# Apple SD Gothic Neo's (0.7042/0.6737 and 1.1350/1.2000 — run `scripts/measure_advance.swift`),
# because layout's numbers sit deliberately *above* the true ones to stay conservative against
# `measure_text.swift`, and that margin has to survive the swap.
#
# Latin is the exception: `layout.CHAR_W_EN`'s 0.44 sits *below* what Apple SD Gothic Neo really
# measures (0.4500), so there is no margin there to preserve — only a 2% optimism the Keynote deck
# happens to absorb. So this one is the measurement itself.
#
# The pitch takes whichever of the two is taller, and for this face that is layout's. NanumSquare
# Round has no U+2022, and 교회 소식 notices are bulleted; CoreText falls back to a system face for
# that one glyph and the **fallback's** taller line then governs the whole line. Measured on the
# 2026-09-06 notices, a bulleted line costs 1.212 rather than the face's own 1.135, which is what
# put a continuation plate one line over. A face taller than layout's still raises this.
CHAR_W_KO = layout.CHAR_W_KO * 0.7042 / 0.6737
CHAR_W_EN = 0.5010
LINE_PITCH = max(layout.LINE_PITCH, layout.LINE_PITCH * 0.1135 / 0.1200)


def line_height(font: float) -> float:
    """``layout.line_height`` at the deck's own line pitch."""
    return layout.line_height(font, LINE_PITCH)

# ── Geometry (1920×1080; transcribed from scripts/render_style_samples.py) ─────
# x, y. The vertical inset is much tighter than the horizontal one because the scripture
# slide is the tallest content in the deck: at the reference 84/59pt it needs five 개역한글 lines
# plus four ESV lines plus both labels, and Keynote fits the same passage only by running from
# y=41 to y=1049 with no frame at all (#178 review). 22 + 12 keeps a visible 네이비 프레임 while
# leaving 1012pt of content — that layout's worst case plus the air the operator opened up under
# the 개역한글 label when they restyled a draft by hand (#178 review, round 3).
FRAME_INSET = (44.0, 22.0)
LYRIC_ZONE_BOTTOM = 72.0     # Option A: distance from the bottom edge
# Half-padding of the black strip around each lyric line (``line_strip`` doubles it into
# ProPresenter's width/height *offset*, which is the total added to the line box). Kept tight
# so the strip hugs the text the way ref-hillsong.png does; the y value is also what opens
# the gap between consecutive strips — the line pitch is fixed by size + line_spacing, so
# less vertical padding means more daylight between lines.
LYRIC_STRIP_PAD = (22.0, 4.0)
CONTENT_INSET = (44.0, 12.0)  # padding inside the frame box
FRAME_BOX = (
    FRAME_INSET[0],
    FRAME_INSET[1],
    CANVAS[0] - 2 * FRAME_INSET[0],
    CANVAS[1] - 2 * FRAME_INSET[1],
)
# Where full-screen slide content lives. Exported because `build` sizes its verse chunks from
# it — the Keynote builder measures the boxes on the open template, but here they are known
# up front, so the packing model and the slide builder must read the same numbers (#178).
CONTENT_RECT = (
    FRAME_BOX[0] + CONTENT_INSET[0],
    FRAME_BOX[1] + CONTENT_INSET[1],
    FRAME_BOX[2] - 2 * CONTENT_INSET[0],
    FRAME_BOX[3] - 2 * CONTENT_INSET[1],
)
# How many wrapped lines each half of a scripture slide is built to hold, at VERSE_KO /
# VERSE_EN. Measured, not guessed: across 삼상 14:1-23 (the 2026-08-30 sermon passage, the
# longest of the recent weeks) the worst verse needs 4.62 개역한글 lines and 3.67 ESV lines at
# 1744pt wide. Budgeting 5 and 4 means every verse in that passage ships at the reference size
# with nothing shrunk, and `build._verse_cues` packs a second verse onto a slide whenever both
# still fit. Raising either without re-checking `CONTENT_RECT` will start clipping.
VERSE_KO_LINES = 5
VERSE_EN_LINES = 4
# A label belongs to the body under it, so it sits close. The 개역한글 label gets noticeably more
# air than the ESV one: that is the operator's own hand-restyle of a draft, where they pushed the
# 84pt Korean body down off its label and left the 59pt English one where it was (#178 review).
VERSE_KO_LABEL_GAP = 28.0
VERSE_EN_LABEL_GAP = 8.0

# Where the church logo sits, matching master.key: top-right on the opening plates (slide 1,
# 1377,45 492×127) and bottom-right on the 표어 / 환영 cards (slide 3, 1372,895 437×97).
LOGO_TOP_RIGHT = (1382.0, 44.0, 480.0, 130.0)
LOGO_BOTTOM_RIGHT = (1400.0, 902.0, 420.0, 114.0)
# ...and centred on the deck's last plate (master slide 170), where it is the only thing on the
# slide. Measured off that page rendered at 72 dpi; the box holds the logo's own 1200×325 aspect,
# and sits a hair above the optical centre the way the deck has it.
LOGO_CENTER = (576.0, 420.0, 768.0, 208.0)

# ── Keyed section labels (#234) ───────────────────────────────────────────────
# Where a keyed label sits, measured off the operator-approved deck rendered at 72 dpi (1 px = 1 pt
# on this canvas): the non-chroma-green bounding box on `draft-2026-08-30.pdf` pages 63/65/68
# (top-left) and 64/66/69 (bottom-centre). Keynote carries one placement per service part; the
# generator ships **both**, because in ProPresenter the operator holds on a cue and picks by where
# the label can sit without covering the live shot. Heights derive from BRUSH_ASPECT so the brush
# variant never has to stretch; the container-less variants just use the same zone.
KEYED_LABEL_PLACEMENTS: dict[str, tuple[tuple[float, float, float, float], float]] = {
    "top": ((20.0, 23.0, 594.0, 594.0 / BRUSH_ASPECT), 70.0),
    "bottom": ((614.0, 892.0, 736.0, 736.0 / BRUSH_ASPECT), 82.0),
}
# Text clearance for the artwork plates is per-plate — see `Plate.inset`, set by the silhouette.
#
# ── The shipped plate is drawn, not artwork (#247) ────────────────────────────
# The artwork was rejected on review as "distant and awkward" beside the rest of the deck, and the
# mismatch was not the interior #247 diagnosed — it was the *vocabulary*. Everything else the deck
# draws is orthogonal, rounded ~10pt (`FRAME_BOX`), and uses gold only as a 1–3pt rule (`_rule`,
# `ANNOUNCE_RAIL_RULE_W`, `LITURGY_RULE_H`). The plate was the one skewed shape in the deck, with a
# 14pt gold slab nearly five times the heaviest rule anywhere else. So the plate is now `FRAME_BOX`
# at label size: the same `el.shape` call, the same fill, the same corner.
#
# The numbers below are read back off the operator's own hand-restyles of two decks (2026-09-05 and
# 2026-09-07) — the "read a markup, not a drag" rule #178 round 3 established. The first pass made
# three changes, each repeated across both placements and so intent rather than noise: the type got
# smaller **and lighter** (Bold 70/82 -> Regular 50/70), the tracking opened up, and the frame's
# white hairline came off. The stroke going is the same call they made restyling the least-dense
# full-screen slides in #178 — "removed borderline to make it cleaner". The second pass took the
# top placement back up to 58 on its own; see `KEYED_PLATES`.
KEYED_LABEL_ANCHOR = {"top": "left", "bottom": "center"}
# What the frame's interior actually *is* on a full-screen slide: the composited backdrop (mean
# 36,41,52 at the shipped strength) with FRAME_FILL_RGBA's 35% ink over it. Pre-blended and
# near-opaque, the same trick the palette above uses for RTF's alpha-less inks — a translucent
# fill cannot be used here, because the green showing through is what the ATEM keyer removes, and
# it would cut a hole in the plate. `test_the_keyed_plate_is_the_frame_interior_of_the_shipped
# _backdrop` re-derives it, so a backdrop swap cannot leave this behind.
KEYED_PLATE_FILL = (0x1B, 0x22, 0x30, 0.93)
KEYED_PLATE_RADIUS = 10.0   # absolute, matching FRAME_BOX's 0.01 × 1036pt shorter side
# The plate hugs its heading. The restyle's two boxes disagree on almost everything, but their
# horizontal padding comes out at 1.54 and 1.57 em — near enough to one number that it is clearly
# what was being eyeballed, and it is why a fixed 594pt bar looked wrong around a short heading.
# Vertical they do not agree (0.31 and 0.17 em), so what is baked is the mean of the two drags in
# absolute points, the same way #244 resolved three disagreeing 문답 anchors.
# Tracking is absolute, not a fraction of the size: both placements land on exactly 7.0pt, where
# in em they disagree (0.121 at the top's 58, 0.100 at the bottom's 70). Two files agreeing on one
# number is what says which model was being eyeballed — it is what made the previous round's
# 0.10 em, back when the same two placements agreed there instead.
KEYED_TRACKING = 7.0


@dataclass(frozen=True)
class DrawnPlate:
    """One placement's plate: type size, horizontal padding in em, vertical padding in points."""

    size: float
    pad_em: float
    pad_y: float


# The two placements no longer share a scale. The bottom is the 2026-09-05 restyle of the
# comparison deck; the top is the operator's 2026-09-07 edit of one cue in the NanumSquare Round
# week deck — "made font and box larger and added spacing between fonts", scoped in the same
# message to the upper-left label. Which is the right instinct: the bottom plate already runs a
# third of the frame, while the top one sits in a corner and has to carry from the back pews.
#
# `pad_y` is back-solved from the box they drew rather than carried across from it: the top plate
# was dragged on a render made while the line pitch was briefly the face's own 1.135, and what they
# were judging is the box's total height (114.72), not the padding left over once `line_height`
# takes its share. So the padding absorbs the pitch correction and the box stays the size it was
# signed off at.
KEYED_PLATES = {
    "top": DrawnPlate(58.0, 1.23, 21.4),
    "bottom": DrawnPlate(70.0, 1.55, 13.5),
}



@dataclass(frozen=True)
class Style:
    """One run's baked look. ``rgb`` is 0–255; ``size`` is points; ``line_spacing`` is the
    *extra* leading in points — the sample CSS line-heights converted as
    ``(line_height - 1) × size``."""

    font: str
    size: float
    rgb: tuple[int, int, int] = INK
    bold: bool = False
    tracking: float = 0.0
    line_spacing: float = 0.0
    align: str = "center"
    family: str = FONT_FAMILY


# Per-section type scale. The #189 sample PNGs were drawn at roughly half these sizes, which
# turned out to be a mock-up scale rather than a projection scale: a large share of the
# congregation is elderly, and the church's own Keynote deck sets scripture at 84pt, 교회 소식 at
# 80pt and the opening plate's heading at 141pt on the same 1920×1080 canvas. So the sizes below
# are transcribed from `주일 2부-2026-08-30-v1.key` — the operator-approved deck — and the frame
# insets above were pulled in to give them the room Keynote's boxes have (#178 review). Anything
# that still overflows shrinks rather than clips: see `elements.text`'s scale_behavior.
# Two of them are no longer Keynote's: the opening plate's sermon title and reference (100/88 there)
# read as shouting on the navy ground, and the operator reset them to 70/60 restyling a draft by
# hand (#178 review, round 3). Their markup is the reference for those, not master.key.
LYRIC_KO = Style(FONT_BOLD, 68, bold=True, tracking=3.0, line_spacing=20.0)
LYRIC_EN = Style(FONT_REGULAR, 34, MUTED, tracking=1.5, line_spacing=10.0)
TITLE = Style(FONT_BOLD, 110, bold=True, tracking=2.0, line_spacing=20.0)
# The two `[ref, 개역한글]` labels are reference furniture, not something the congregation
# reads across the sanctuary, so they stay small — Keynote sets them at 64/56 in their own
# boxes above each body, and every point spent on them is a point the body cannot have.
VERSE_LABEL = Style(FONT_BOLD, 44, ACCENT, bold=True, align="left")
VERSE_NUMBER = Style(FONT_BOLD, 62, ACCENT, bold=True, align="left")
VERSE_KO = Style(FONT_REGULAR, 84, line_spacing=6.0, align="left")
VERSE_EN_LABEL = Style(FONT_BOLD, 40, ACCENT, bold=True, align="left")
VERSE_EN = Style(FONT_REGULAR, 59, MUTED, line_spacing=6.0, align="left")
# 교회 소식 (라벨 레일, #233). Gold is furniture here — the eyebrow, the rule, the rail labels,
# the counter — and the notice's own title is white, which is the hierarchy the old gold-title
# plate never had. The labels sit below the 60pt body floor for the same reason the verse labels
# do: they name the value beside them rather than being read across the sanctuary.
ANNOUNCE_HEADING = Style(FONT_BOLD, 44, ACCENT, bold=True, tracking=8.0, align="left")
ANNOUNCE_COUNTER = Style(FONT_BOLD, 44, ACCENT, bold=True, tracking=4.0, align="right")
ANNOUNCE_TITLE = Style(FONT_BOLD, 88, bold=True, line_spacing=12.0, align="left")
ANNOUNCE_LABEL = Style(FONT_BOLD, 52, ACCENT, bold=True, line_spacing=10.0, align="right")
ANNOUNCE_VALUE = Style(FONT_REGULAR, 64, line_spacing=10.0, align="left")
ANNOUNCE_DETAIL = Style(FONT_REGULAR, 64, MUTED, line_spacing=20.0, align="left")
# Regular, not Bold, and smaller than Keynote's 70/82 — the operator's own restyle (#247). A keyed
# label annotates the shot rather than being read across the sanctuary, so it is not held to the
# body floor the divider and scripture are; size and tracking come from KEYED_PLATES.
KEYED_LABEL = Style(FONT_REGULAR, 58, tracking=KEYED_TRACKING)
DIVIDER_KO = Style(FONT_BOLD, 190, bold=True, tracking=12.0)
DIVIDER_SUB = Style(FONT_BOLD, 76, ACCENT, bold=True, tracking=2.0)
# Two more headings wear the divider plate, and neither is a section name. #249 gave the sermon
# title the divider look and #250 the 말씀 reference plate; the operator reset both by hand in
# ProPresenter, and the sizes and gaps below are read straight off those cues.
#
# 190pt is sized for a four-glyph section name. Measured through CoreText at the 1744pt content
# width, 예배의 부름 sets 945pt wide — 54% of the box, type with margins around it. The same size
# runs 사무엘상 14:23-52 out to 1571pt (90%, edge to edge) and 데살로니가전서 5:12-24 to 1968pt,
# which wraps onto a second line outright. At 150 they come back to 73% and 91%: one line always,
# with the optical weight a section name has. A sermon title is a whole sentence and drops further.
#
# The gaps under them grow as the type shrinks — 40pt of air reads right beneath 190pt and cramped
# beneath 135. A smaller heading needs *more* room under it, not the same.
VERSE_DIVIDER_KO = replace(DIVIDER_KO, size=150)
SERMON_TITLE_KO = replace(DIVIDER_KO, size=135)
LITURGY_TITLE = Style(FONT_BOLD, 48, ACCENT, bold=True, tracking=12.0)
LITURGY_BODY = Style(FONT_BOLD, 72, bold=True, line_spacing=22.0)
# The leader's line in the responsive 사도신경 (#244). Gold, but the *same size* as the answer:
# the pastor reads it aloud and the congregation still follows it on screen, so it is held to
# the same legibility floor as the body — it is a different voice, not smaller print.
LITURGY_QUESTION = replace(LITURGY_BODY, rgb=ACCENT)
SERVICE_HEADING = Style(FONT_BOLD, 138, bold=True, line_spacing=10.0)
SERVICE_NOTICE = Style(FONT_REGULAR, 37, MUTED, line_spacing=8.0)
SERVICE_DATE = Style(FONT_BOLD, 79, bold=True, tracking=2.0)
SERVICE_TITLE = Style(FONT_BOLD, 70, ACCENT, bold=True, line_spacing=12.0)
SERVICE_REF = Style(FONT_BOLD, 60, ACCENT, bold=True, line_spacing=12.0)
CLOSING_BLESSING = Style(FONT_REGULAR, 75)
NOTE = Style(FONT_REGULAR, 18, BLACK, align="left")  # per-slide notes pane, not on the canvas
CARD_BODY = Style(FONT_BOLD, 80, bold=True, line_spacing=26.0)
CARD_ACCENT = Style(FONT_BOLD, 80, ACCENT, bold=True, line_spacing=26.0)
# The 폐회 안내 farewell, under the rule (#249). Regular and muted at ~0.7 of the card body, so it
# reads as the courtesy it is rather than as a third instruction — Keynote sets it smaller too.
CARD_FAREWELL = Style(FONT_REGULAR, 56, MUTED, line_spacing=20.0)

# ── Liturgy geometry (#244) ───────────────────────────────────────────────────
# The 사도신경 / 주기도문 header band: the title's own line plus the air under it. Derived rather
# than guessed — it used to be a bare 110.0, which cost 22pt the body could not spare on the
# longest recitation slide. The gap is `VERSE_KO_LABEL_GAP`, the air the operator opened under
# the 개역한글 label restyling a draft by hand (#178 review, round 3): the same relationship, a
# label and the body it belongs to.
LITURGY_TITLE_GAP = VERSE_KO_LABEL_GAP
LITURGY_HEADER_H = layout.line_height(LITURGY_TITLE.size) + LITURGY_TITLE_GAP
# The 문답 slide's three anchors, all read back off the operator's own hand-restyle of
# `Creed 244 v1.pro` (#244 review). They dragged all three 문답 slides, and no two agreed —
# the air around the bar came out 91/80, 46/46 and 59/68 — so what is baked here is the mean
# of the three, which lands within ~1pt of each anchor's average: question top 153.0 (theirs
# 153.1), bar 326.5 (327.5), answer top 393.8 (395.1). The shape the drags agree on is what
# matters: the question is **pinned** under the title rather than floating in a centred
# composite, the bar gets far more air than the 24pt it shipped with, and the answer hangs
# from the bar — a short answer leaves the foot of the slide open, which is how their 문답 1
# reads and is deliberate, not a hole to fill.
LITURGY_QUESTION_GAP = 31.0
LITURGY_RULE_W = 360.0
LITURGY_RULE_H = 3.0
LITURGY_RULE_GAP = 65.0

# The air above and below the 폐회 안내 card's rule (#249). Same idiom as the 문답 bar, but the
# whole assembly is centred here rather than pinned: this card has no title band to hang from.
CLOSING_RULE_GAP = 70.0


# ── Slide builders ────────────────────────────────────────────────────────────

def _slide(*, background: tuple[int, int, int] | None = None) -> slide_pb2.Slide:
    """An empty 1920×1080 slide. Canvas size is per-slide in ProPresenter, not per-document."""
    slide = slide_pb2.Slide()
    slide.uuid.string = el.new_uuid()
    slide.size.width, slide.size.height = CANVAS
    if background is not None:
        slide.draws_background_color = True
        el.set_color(slide.background_color, background)
    return slide


def _front_to_back(slide: slide_pb2.Slide) -> slide_pb2.Slide:
    """Flip the element list into ProPresenter's paint order.

    ProPresenter stores elements front-to-back — ``elements[0]`` is the *topmost* layer (in a
    PP-authored deck the full-bleed background box is the last element, under the text). The
    builders above add background first and text last because that reads naturally, so the
    list gets reversed here on the way out.
    """
    ordered = [e for e in reversed(slide.elements)]
    del slide.elements[:]
    for element in ordered:
        slide.elements.add().CopyFrom(element)
    return slide


def _framed(slide: slide_pb2.Slide, *, frame: bool = True) -> tuple[float, float, float, float]:
    """Draw the Option 3 backdrop — navy tint + frame box — and return the content rect.

    ``frame=False`` keeps the tint but drops the outline. The opening/closing plates and the
    fixed-wording cards use it: they are the least dense slides in the deck, and the operator
    took the outline off all three restyling a draft by hand — "removed borderline to make it
    cleaner" (#178 review, round 3). The frame stays wherever content reaches the edges — the
    dividers, scripture, liturgy and 교회 소식.

    The sample's blurred-photo backdrop goes in first, under the tint. ProPresenter's own
    ``backgroundEffect.backgroundBlur`` would have supplied the blur for free, but 21.4 renders
    it as a placeholder and crashes on selection (verified 2026-08-13), so ``BACKDROP`` is
    pre-blurred offline by ``scripts/make_backdrop.py`` and placed as an ordinary image (#224).
    It fills the frame — a background photo is the one thing in the deck that may be cropped,
    unlike ``_logo``'s artwork. The callers keep their ``NAVY`` slide background underneath as
    the fallback: a media element whose file has gone missing draws *nothing*, silently, and an
    unbacked slide renders black.
    """
    el.image(slide, (0.0, 0.0, *CANVAS), BACKDROP.image)
    el.shape(slide, (0.0, 0.0, *CANVAS), fill=TINT_RGBA)
    if frame:
        el.shape(
            slide,
            FRAME_BOX,
            fill=FRAME_FILL_RGBA,
            stroke=(FRAME_STROKE_RGBA, FRAME_STROKE_WIDTH),
            roundness=FRAME_RADIUS,
        )
    return CONTENT_RECT


def _logo(slide: slide_pb2.Slide, rect: tuple[float, float, float, float]) -> None:
    """Place the church logo. ``fill_frame=False`` so it letterboxes inside ``rect`` — the
    artwork's aspect must never be cropped the way a background photo can be."""
    el.image(slide, rect, LOGO, fill_frame=False)


def _wrapped_height(runs: list[rtf.Run], width: float, scale: float) -> float:
    """Estimated height of ``runs`` laid into a box ``width`` wide at ``scale``× their sizes.

    Same wrapping model as ``bible.layout`` (average glyph advance / font size), walked run by
    run because one paragraph mixes sizes — a gold verse number then the verse body. Each line
    costs ``layout.LINE_PITCH`` × its largest font plus the style's extra leading, the last line
    included: ProPresenter reserves the line spacing *after* the final line too, so a box short
    by even part of one leading is a box the app flags (#178 review, confirmed against two decks
    the operator marked up by hand).
    """
    lead = runs[0][1].line_spacing * scale
    lines: list[float] = []
    column, line_size = 0.0, 0.0
    for text, style in runs:
        size = style.size * scale
        char_w = CHAR_W_KO if any("가" <= c <= "힣" for c in text) else CHAR_W_EN
        paragraphs = text.split("\n")
        for i, paragraph in enumerate(paragraphs):
            if i:
                lines.append(line_size)
                column, line_size = 0.0, 0.0
            # A run that ends in a newline leaves an empty tail paragraph: that is the *next*
            # run's line, not another line of this one, so this run's size must not claim it.
            # An empty paragraph anywhere earlier is a real blank line, and does.
            if paragraph or i < len(paragraphs) - 1:
                line_size = max(line_size, size)
            column += len(paragraph) * size * char_w
            while column > width:
                lines.append(line_size)
                column -= width
    lines.append(line_size)
    return sum(s * LINE_PITCH for s in lines) + lead * len(lines)


def _fit_scale(runs: list[rtf.Run], width: float, height: float, floor: float = 0.55) -> float:
    """The largest scale ≤ 1 at which ``runs`` fit a ``width``×``height`` box.

    The church's Keynote deck leans on "shrink text to fit" for the occasional over-long
    announcement or verse, and the generated deck needs the same safety net — but
    ProPresenter's own ``SCALE_BEHAVIOR_SCALE_FONT_DOWN`` is not it: PP shrinks until the text
    fits *without wrapping*, which drops a four-line 개역한글 verse to ~20pt on one line
    (measured on PP 21.4, #178 review). So the fitting is done here, at authoring time, and the
    slide ships at a size that genuinely fits.
    """
    for step in range(int((1.0 - floor) * 20) + 1):
        scale = 1.0 - step * 0.05
        if _wrapped_height(runs, width, scale) <= height:
            return scale
    return floor


def _at(text: str, style: Style, scale: float) -> rtf.Run:
    """One run at ``scale`` — size and leading shrink together, so the block keeps its rhythm."""
    if scale == 1.0:
        return text, style
    return text, replace(style, size=style.size * scale, line_spacing=style.line_spacing * scale)


def _scaled(runs: list[rtf.Run], width: float, height: float) -> list[rtf.Run]:
    """``runs`` with every style shrunk by ``_fit_scale`` (a no-op when they already fit)."""
    scale = _fit_scale(runs, width, height)
    return [_at(text, style, scale) for text, style in runs]


def _rule(
    slide: slide_pb2.Slide,
    y: float,
    width: float = 96.0,
    height: float = 3.0,
    x: float | None = None,
) -> None:
    """The gold hairline the samples put under headings and between KO and EN.

    Centred on the canvas unless ``x`` is given — the 교회 소식 plate is set left, so its rule
    runs the content width from the same margin its eyebrow and title start at.
    """
    el.shape(slide, (CANVAS[0] / 2 - width / 2 if x is None else x, y, width, height),
             fill=(*ACCENT, 0.9))


def worship_lyric_ko(lines: list[str]) -> slide_pb2.Slide:
    """Option A lower-third: bold white lyrics on per-line black strips, over live camera.

    Backed with CHROMA_GREEN, not left transparent — ProPresenter renders an empty background
    as black, which would cover the camera instead of keying out on the ATEM (#192).
    """
    slide = _slide(background=CHROMA_GREEN)
    height = LYRIC_KO.size * 1.6 * len(lines) + 2 * LYRIC_STRIP_PAD[1]
    rect = (0.0, CANVAS[1] - LYRIC_ZONE_BOTTOM - height, CANVAS[0], height)
    element = el.text(slide, rect, rtf.plain("\n".join(lines), LYRIC_KO), LYRIC_KO)
    el.line_strip(element, (*BLACK, 1.0), pad=LYRIC_STRIP_PAD)
    return _front_to_back(slide)


def worship_lyric_bilingual(korean: str, english: str) -> slide_pb2.Slide:
    """Option A lower-third with a smaller English line under the Korean.

    Unused for now: worship lyrics are Korean-only until a pre-filled KO+EN lyric source
    exists (#228). Keyed green for the same reason as ``worship_lyric_ko``.
    """
    slide = _slide(background=CHROMA_GREEN)
    ko_style = replace(LYRIC_KO, size=66)
    ko_h = ko_style.size * 1.6 + 2 * LYRIC_STRIP_PAD[1]
    en_h = LYRIC_EN.size * 1.8 + 2 * LYRIC_STRIP_PAD[1]
    top = CANVAS[1] - 64.0 - ko_h - en_h
    ko = el.text(slide, (0.0, top, CANVAS[0], ko_h), rtf.plain(korean, ko_style), ko_style)
    el.line_strip(ko, (*BLACK, 1.0), pad=LYRIC_STRIP_PAD)
    en = el.text(
        slide,
        (0.0, top + ko_h, CANVAS[0], en_h),
        rtf.plain(english.upper(), LYRIC_EN),
        LYRIC_EN,
    )
    el.line_strip(en, (*BLACK, 1.0), pad=(26.0, 9.0))
    return _front_to_back(slide)


def song_banner(title: str) -> slide_pb2.Slide:
    """Keyed lower-third song-title banner — the worship medley's per-song title.

    The congregation sees a song title as a *narrow banner over the live band shot* today
    (config/slide_map.yaml: "per song: blank-green separator + title slide + N lyric slides"),
    so this is the Option A strip idiom in the lyric zone, one line, set exactly like the
    lyrics — same type as the lyrics it introduces, so the two read as one banner that simply
    changes text. The sections that genuinely read as a title card — 고백의 찬양, 성가대, the
    sermon title — use ``section_divider`` instead (#178, #249).
    """
    slide = _slide(background=CHROMA_GREEN)
    height = LYRIC_KO.size * 1.6 + 2 * LYRIC_STRIP_PAD[1]
    rect = (0.0, CANVAS[1] - LYRIC_ZONE_BOTTOM - height, CANVAS[0], height)
    element = el.text(slide, rect, rtf.plain(title, LYRIC_KO), LYRIC_KO)
    el.line_strip(element, (*BLACK, 1.0), pad=LYRIC_STRIP_PAD)
    return _front_to_back(slide)


def verse_rects() -> dict[str, tuple[float, float, float, float]]:
    """The four boxes of a scripture slide, plus the y of the gold rule between the languages.

    Shared with ``build._verse_cues``, which has to pack verses to exactly the boxes this lays
    them into. The four heights are fixed by the type scale (``VERSE_*_LINES`` lines at each
    style's own pitch); the rhythm is the Keynote deck's (master 141-163): each label sits hard
    against the body it introduces, the 개역한글 block hangs from the top of the content rect and
    the ESV block from the bottom, and all the slack collects in the middle — where a gap reads
    as the division between two languages rather than as a slide that failed to fill.
    """
    x, y, w, h = CONTENT_RECT
    ko_label_h = line_height(VERSE_LABEL.size)
    en_label_h = line_height(VERSE_EN_LABEL.size)
    ko_body_h = VERSE_KO_LINES * (VERSE_KO.size * LINE_PITCH + VERSE_KO.line_spacing)
    en_body_h = VERSE_EN_LINES * (VERSE_EN.size * LINE_PITCH + VERSE_EN.line_spacing)

    ko_body_y = y + ko_label_h + VERSE_KO_LABEL_GAP
    en_body_y = y + h - en_body_h
    en_label_y = en_body_y - VERSE_EN_LABEL_GAP - en_label_h
    return {
        "ko_label": (x, y, w, ko_label_h),
        "ko_body": (x, ko_body_y, w, ko_body_h),
        "rule_y": ((ko_body_y + ko_body_h + en_label_y) / 2, 0.0, 0.0, 0.0),
        "en_label": (x, en_label_y, w, en_label_h),
        "en_body": (x, en_body_y, w, en_body_h),
    }


def verse_fullscreen(
    ko_label: str,
    ko_verses: list[tuple[int, str]],
    en_label: str,
    en_verses: list[tuple[int, str]],
) -> slide_pb2.Slide:
    """Bilingual scripture: 개역한글 above, a gold rule, then ESV — verse numbers in gold.

    Laid out like the church's Keynote slide (master 141-163): each language gets a small
    reference label in its own box above a body box, rather than the label sharing the body's
    box — an inline label costs the body a whole line of its own pitch, which is what pushed
    the long verses of 삼상 14 past the bottom of the slide (#178 review).
    """
    slide = _slide(background=NAVY)
    _framed(slide)
    rects = verse_rects()

    ko_runs: list[rtf.Run] = []
    for i, (number, text) in enumerate(ko_verses):
        ko_runs += [(("\n" if i else "") + f"{number} ", VERSE_NUMBER), (text, VERSE_KO)]
    en_runs: list[rtf.Run] = []
    for i, (number, text) in enumerate(en_verses):
        en_runs += [
            (("\n" if i else "") + f"{number} ", replace(VERSE_NUMBER, size=44)),
            (text, VERSE_EN),
        ]

    el.text(slide, rects["ko_label"], rtf.plain(ko_label, VERSE_LABEL), VERSE_LABEL,
            valign="top")
    el.text(slide, rects["en_label"], rtf.plain(en_label, VERSE_EN_LABEL), VERSE_EN_LABEL,
            valign="top")
    # `build._verse_cues` packs each slide to these boxes, so `_scaled` is a floor-level safety
    # net for the passage that overruns anyway — one verse too long for a slide of its own.
    for key, runs, base in (("ko_body", ko_runs, VERSE_KO), ("en_body", en_runs, VERSE_EN)):
        rect = rects[key]
        el.text(slide, rect, rtf.document(_scaled(runs, rect[2], rect[3])), base, valign="top")
    _rule(slide, rects["rule_y"][0], width=84.0, height=1.0)
    return _front_to_back(slide)


# 교회 소식 layout. The header (eyebrow + rule) is fixed; everything under it is measured and
# then centred, because the notices are short: across the 112 items of the last 14 weeks the
# median one fills 54% of the plate and 38% of them under half, so a top-anchored block left the
# bottom of nearly every slide empty (#233).
ANNOUNCE_HEADER_H = 104.0    # eyebrow + gold rule, above the notice
ANNOUNCE_LABEL_W = 360.0     # the rail's gold label column ("피택 시무장로" is the widest seen)
ANNOUNCE_RAIL_GAP = 26.0     # label -> hairline -> value
ANNOUNCE_RAIL_RULE_W = 3.0
ANNOUNCE_VALUE_DX = ANNOUNCE_LABEL_W + 2 * ANNOUNCE_RAIL_GAP + ANNOUNCE_RAIL_RULE_W
ANNOUNCE_TITLE_GAP = 44.0
ANNOUNCE_ROW_GAP = 18.0
ANNOUNCE_BODY_GAP = 48.0
# Headroom over the estimate on every box. ``_wrapped_height`` models CoreText rather than being
# it (``scripts/audit_pro_layout.py`` is what measures for real), and here each box is sized to
# its own content instead of to one generous fixed rect, so a point or two of drift would show
# up as a flagged slide.
ANNOUNCE_SLACK = 10.0

_ANNOUNCE_GAPS = {("title", "row"): ANNOUNCE_TITLE_GAP, ("title", "body"): ANNOUNCE_TITLE_GAP,
                  ("row", "row"): ANNOUNCE_ROW_GAP, ("row", "body"): ANNOUNCE_BODY_GAP}

_AnnounceBlock = tuple[str, float, object]


def _by_script(text: str, style: Style) -> list[rtf.Run]:
    """``text`` cut into same-style runs at each Hangul/Latin boundary, for measuring only.

    ``_wrapped_height`` picks one average glyph advance per *run* — 0.83 em if the run holds any
    Hangul, 0.44 if it does not — which is right for a verse and badly wrong for a 교회 소식 rail,
    where a value like "9/20/2026 – 1/31/2027 (14주)" is almost all Latin and one 주 makes the
    whole thing measure half again too wide. Splitting the string at the boundary lets the same
    model weigh each side properly. The drawn RTF is unaffected: concatenating same-style runs
    produces the identical document.
    """
    return [(part, style) for part in re.findall(r"[가-힣]+|[^가-힣]+", text) if part]


def _announce_blocks(item: announce.Item) -> list[_AnnounceBlock]:
    """One ``(kind, height, payload)`` per drawn element of a 교회 소식 notice, top to bottom.

    Shared by the splitter and the slide builder so the two cannot disagree about what fits.
    """
    _, _, w, _ = CONTENT_RECT
    value_w = w - ANNOUNCE_VALUE_DX
    blocks: list[_AnnounceBlock] = [(
        "title",
        _wrapped_height(_by_script(item.title, ANNOUNCE_TITLE), w, 1.0) + ANNOUNCE_SLACK,
        item.title,
    )]
    for label, value in item.rows:
        # An unlabelled row (a bare roster the bulletin never captioned) is measured on its
        # value alone; the label column stays empty for the operator to fill in review.
        height = max(
            _wrapped_height(_by_script(label, ANNOUNCE_LABEL), ANNOUNCE_LABEL_W, 1.0)
            if label else 0.0,
            _wrapped_height(_by_script(value, ANNOUNCE_VALUE), value_w, 1.0),
        )
        blocks.append(("row", height + ANNOUNCE_SLACK, (label, value)))
    if item.paragraphs:
        body = "\n\n".join(item.paragraphs)
        blocks.append((
            "body",
            _wrapped_height(_by_script(body, ANNOUNCE_DETAIL), w, 1.0) + ANNOUNCE_SLACK,
            body,
        ))
    return blocks


def _announce_height(blocks: list[_AnnounceBlock]) -> float:
    """Total height of ``blocks`` including the gaps between them."""
    total = 0.0
    for i, (kind, height, _) in enumerate(blocks):
        if i:
            total += _ANNOUNCE_GAPS.get((blocks[i - 1][0], kind), ANNOUNCE_ROW_GAP)
        total += height
    return total


def _announce_part(title: str, rows: list[tuple[str, str]], lines: list[tuple[int, str]]):
    """One plate's worth of packed units, back as an ``Item``.

    ``lines`` carries each prose line with the index of the paragraph it came from, so the
    paragraph breaks the bulletin wrote survive being packed line by line.
    """
    paragraphs: list[list[str]] = []
    previous: int | None = None
    for index, text in lines:
        if index == previous:
            paragraphs[-1].append(text)
        else:
            paragraphs.append([text])
        previous = index
    return announce.Item(title, tuple(rows), tuple("\n".join(p) for p in paragraphs))


def split_announcement(item: announce.Item) -> list[announce.Item]:
    """``item`` cut into as many plates as it takes to ship at **full size**.

    The old plate shrank instead — 4 of the last 112 notices came out under the type scale the
    operator approved, the worst at 0.85 — and shrinking is the wrong answer for a congregation
    that skews elderly (#233). Every plate repeats the title, so a notice that runs onto a second
    one still reads as one notice; 교회 소식 has no "one verse per slide" rule to respect the way
    scripture does.

    Packing is greedy and line-by-line: the rail rows go on first and the prose fills in behind
    them, cut at the line breaks the bulletin itself wrote (a schedule, a list of names — the
    church's own units). Chunking the prose *ahead* of the rail is what an earlier cut of this
    did, and it spent a whole plate on a lone 날짜 row while the prose waited on the next one.

    A single line too tall for a plate on its own is the one case this cannot fix; none exists in
    the last 14 weeks, and ``scripts/audit_pro_layout.py`` is what would catch a future one.
    """
    available = CONTENT_RECT[3] - ANNOUNCE_HEADER_H
    units: list[tuple[str, object]] = [("row", row) for row in item.rows]
    units += [("line", (index, line))
              for index, paragraph in enumerate(item.paragraphs)
              for line in paragraph.split("\n")]

    parts: list[announce.Item] = []
    rows: list[tuple[str, str]] = []
    lines: list[tuple[int, str]] = []
    for kind, unit in units:
        trial_rows = rows + [unit] if kind == "row" else rows
        trial_lines = lines if kind == "row" else lines + [unit]
        trial = _announce_part(item.title, trial_rows, trial_lines)
        if (rows or lines) and _announce_height(_announce_blocks(trial)) > available:
            parts.append(_announce_part(item.title, rows, lines))
            rows, lines = ([unit], []) if kind == "row" else ([], [unit])
        else:
            rows, lines = trial_rows, trial_lines
    parts.append(_announce_part(item.title, rows, lines))
    return parts


def announcement(
    heading: str, item: announce.Item, index: int = 1, total: int = 1
) -> slide_pb2.Slide:
    """교회 소식 — one notice as a white title over a gold 날짜/장소/문의 rail and its prose.

    ``item`` is already sized to one plate by ``split_announcement``. The heading stays a small
    gold eyebrow rather than a plate title (the section is announced once, on its own divider),
    and the counter beside it tells a congregation eight or nine notices deep how many are left.
    """
    slide = _slide(background=NAVY)
    x, y, w, h = _framed(slide)
    el.text(slide, (x, y, w / 2, 56.0), rtf.plain(heading, ANNOUNCE_HEADING),
            ANNOUNCE_HEADING, valign="top")
    if total > 1:
        counter = f"{index} / {total}"
        el.text(slide, (x + w / 2, y, w / 2, 56.0), rtf.plain(counter, ANNOUNCE_COUNTER),
                ANNOUNCE_COUNTER, valign="top")
    _rule(slide, y + 78.0, width=w, height=2.0, x=x)

    blocks = _announce_blocks(item)
    cursor = y + ANNOUNCE_HEADER_H + max(
        0.0, (h - ANNOUNCE_HEADER_H - _announce_height(blocks)) / 2
    )
    rail: list[float] = []
    for i, (kind, height, payload) in enumerate(blocks):
        if i:
            cursor += _ANNOUNCE_GAPS.get((blocks[i - 1][0], kind), ANNOUNCE_ROW_GAP)
        if kind == "row":
            label, value = payload
            if label:
                el.text(slide, (x, cursor, ANNOUNCE_LABEL_W, height),
                        rtf.plain(label, ANNOUNCE_LABEL), ANNOUNCE_LABEL, valign="top")
            el.text(slide, (x + ANNOUNCE_VALUE_DX, cursor, w - ANNOUNCE_VALUE_DX, height),
                    rtf.plain(value, ANNOUNCE_VALUE), ANNOUNCE_VALUE, valign="top")
            rail += [cursor, cursor + height]
        else:
            style = ANNOUNCE_TITLE if kind == "title" else ANNOUNCE_DETAIL
            el.text(slide, (x, cursor, w, height), rtf.plain(payload, style), style, valign="top")
        cursor += height
    if rail:
        el.shape(slide, (x + ANNOUNCE_LABEL_W + ANNOUNCE_RAIL_GAP, rail[0],
                         ANNOUNCE_RAIL_RULE_W, rail[-1] - rail[0]), fill=(*ACCENT, 0.55))
    return _front_to_back(slide)


def _heading_plate(
    heading: str,
    subtitle: str,
    style: Style,
    *,
    frac: float,
    rule_gap: float,
    sub_gap: float,
) -> slide_pb2.Slide:
    """A heading bottomed out at ``frac`` of the content rect, a gold rule under it, a subtitle.

    ``section_divider`` and ``sermon_title`` are this plate at two scales — see their tuning
    constants for why the sermon title is not simply a divider with smaller type.

    The heading is fitted rather than set flat: a section name is four glyphs and always fits,
    but a sermon title is a sentence, and at full size a long one wrapped past the bottom of its
    box. ``_scaled`` is a no-op for every fixed heading in the deck.
    """
    slide = _slide(background=NAVY)
    x, y, w, h = _framed(slide)
    heading_box = (x, y, w, h * frac)
    el.text(
        slide,
        heading_box,
        rtf.document(_scaled([(heading, style)], w, heading_box[3])),
        style,
        valign="bottom",
    )
    _rule(slide, y + h * frac + rule_gap, width=90.0)
    if subtitle:
        el.text(
            slide,
            (x, y + h * frac + sub_gap, w, 140.0),
            rtf.plain(subtitle, DIVIDER_SUB),
            DIVIDER_SUB,
            valign="top",
        )
    return _front_to_back(slide)


def section_divider(heading: str, subtitle: str = "") -> slide_pb2.Slide:
    """Section heading slide (예배의 부름 / 봉 헌 / 교회 소식 …) with the gold rule and subtitle.

    The subtitle is bare — the week's song title or scripture reference, no brackets. master.key
    writes ``[ 믿음으로 우리는 ]``; the operator dropped the brackets across the divider slides
    restyling a draft, since the gold rule above already separates it (#178 review, round 3).
    """
    return _heading_plate(heading, subtitle, DIVIDER_KO, frac=0.62, rule_gap=40.0, sub_gap=96.0)


def verse_divider(ref: str, en_ref: str = "") -> slide_pb2.Slide:
    """The 말씀 reference plate, where the *reference* is the heading (#250).

    A section divider with a reference in the heading slot, and the section-name size is wrong
    for it — see ``VERSE_DIVIDER_KO``. The English reference beneath is bare, like every other
    divider subtitle: the scripture slides keep their ``[삼상 14:23-52, 개역한글]`` brackets
    because those labels sit inside a body, and here the gold rule already does the separating
    (the #178 round-3 rule, applied to the one divider subtitle that had missed it).
    """
    return _heading_plate(
        ref, en_ref, VERSE_DIVIDER_KO, frac=0.586, rule_gap=52.0, sub_gap=131.0
    )


def sermon_title(title: str, ref: str = "") -> slide_pb2.Slide:
    """The week's sermon title over its reference — the divider idiom at sentence scale (#250).

    Same plate as ``section_divider`` and deliberately so (#249): the operator reads the deck by
    its gold-ruled headings, and the sermon title is one of them. Only the scale differs, and the
    numbers are the operator's own — see ``SERMON_TITLE_KO``. ``ref`` is the Korean reference with
    its book spelled out (``bible.ref.korean_ref``), matching the plate above it.
    """
    return _heading_plate(title, ref, SERMON_TITLE_KO, frac=0.55, rule_gap=82.0, sub_gap=143.0)


def _text_width(text: str, style: Style) -> float:
    """One line's laid-out width, on ``_wrapped_height``'s model: an average glyph advance per
    script, plus the tracking that sits between the glyphs."""
    char_w = CHAR_W_KO if any("가" <= c <= "힣" for c in text) else CHAR_W_EN
    return len(text) * style.size * char_w + max(0, len(text) - 1) * style.tracking


def _drawn_plate(
    slide: slide_pb2.Slide,
    zone: tuple[float, float, float, float],
    heading: str,
    style: Style,
    placement: str,
    plate: DrawnPlate,
) -> tuple[float, float, float, float]:
    """Draw the keyed plate as ``FRAME_BOX`` at label size; return the rect left for the heading.

    The box hugs the heading rather than filling ``zone``, and keeps that zone's anchor: the
    top-left label stays pinned to its measured corner, the bottom one centres — on the *canvas*,
    which is where the operator moved it (960, not the measured rect's 982). So a longer heading
    grows the plate outward without ever sliding the label off the framing it was placed for.

    No stroke, deliberately: the operator took the frame's hairline off both plates (#247), the
    same call they made on the least-dense full-screen slides in #178.
    """
    pad = plate.pad_em * style.size
    w = _text_width(heading, style) + 2 * pad
    h = line_height(style.size) + 2 * plate.pad_y
    x, y, _zw, zh = zone
    if KEYED_LABEL_ANCHOR[placement] == "center":
        x, y = CANVAS[0] / 2 - w / 2, y + (zh - h) / 2
    el.shape(
        slide, (x, y, w, h), fill=KEYED_PLATE_FILL, roundness=KEYED_PLATE_RADIUS / min(w, h)
    )
    return x + pad, y, w - 2 * pad, h


def keyed_label(heading: str, placement: str = "top", variant: str = "") -> slide_pb2.Slide:
    """Section heading keyed over the live camera (회개로의 초대 / 죄사함의 선포 / 합심 기도, #234).

    These sections *annotate* the shot rather than replace it, so unlike ``section_divider`` the
    slide is chroma-green backed and carries only a small label — an unbacked slide renders black
    and covers the camera instead of keying (#192), the same reason the sung-lyric styles are
    backed.

    The plate is **drawn** — ``FRAME_BOX`` at label size, hugging the heading (#247). Passing a
    ``variant`` places a ``KEYED_ART`` PNG in the measured zone instead, which is what #234's
    bake-off picked and what the deck shipped until the operator's restyle; they are kept only so
    the #241 style review can put the drawn plate beside them.

    Both placements exist, and both are emitted per section: Keynote carries one per service part,
    but in ProPresenter the operator holds on a cue and chooses by where the label can sit without
    covering the live shot.
    """
    slide = _slide(background=CHROMA_GREEN)
    zone, art_size = KEYED_LABEL_PLACEMENTS[placement]
    if variant:
        style = replace(KEYED_LABEL, font=FONT_BOLD, bold=True, size=art_size, tracking=2.0)
        inset = zone[2] * KEYED_ART[variant].inset
        rect = (zone[0] + inset, zone[1], zone[2] - 2 * inset, zone[3])
        el.image(slide, zone, KEYED_ART[variant].image, fill_frame=False)
    else:
        plate = KEYED_PLATES[placement]
        style = replace(KEYED_LABEL, size=plate.size, tracking=KEYED_TRACKING)
        rect = _drawn_plate(slide, zone, heading, style, placement, plate)
    element = el.text(
        slide, rect, rtf.document(_scaled([(heading, style)], rect[2], rect[3])), style
    )
    if variant:
        # Artwork only. The drawn plate is its own separation from the shot, and nothing else in
        # the deck shadows its type; the PNGs' soft or unoutlined edges leave white glyphs sitting
        # almost directly on the camera.
        el.shadow(element)
    return _front_to_back(slide)


def _liturgy_body_rect(slide: slide_pb2.Slide, title: str) -> tuple[float, float, float, float]:
    """Draw the liturgy ground and its gold spaced title; return the rect left for the body."""
    x, y, w, h = _framed(slide)
    el.text(
        slide,
        (x, y, w, line_height(LITURGY_TITLE.size)),
        rtf.plain(title, LITURGY_TITLE),
        LITURGY_TITLE,
    )
    return x, y + LITURGY_HEADER_H, w, h - LITURGY_HEADER_H


def liturgy(title: str, lines: list[str]) -> slide_pb2.Slide:
    """Fixed-wording full-screen liturgy (사도신경 recitation / 주기도문) — title over the body.

    The body is **centred** in what the header leaves, not top-aligned. These blocks are as long
    as the church wrote them and nothing re-chunks them, so their heights run from 436pt (주기도문
    slide 1) to 873pt (사도신경 slide 1) in the same box: top-aligned, the text hugged the top of
    one slide and ran edge to edge on the next, and the block visibly jumped as the operator
    advanced (#244).
    """
    slide = _slide(background=NAVY)
    x, y, w, h = _liturgy_body_rect(slide, title)
    body: list[rtf.Run] = [("\n".join(lines), LITURGY_BODY)]
    el.text(slide, (x, y, w, h), rtf.document(_scaled(body, w, h)), LITURGY_BODY)
    return _front_to_back(slide)


def liturgy_responsive(title: str, question: str, answer: list[str]) -> slide_pb2.Slide:
    """The 문답 form of 사도신경 — the leader's question in gold over a hairline, the
    congregation's answer in white below it (#244).

    The pastor reads the question and the congregation reads the answer, but master.key sets both
    in one 72pt white block, which leaves nobody able to see which lines are theirs. Colour plus a
    rule is the deck's own way of marking that kind of break (``_rule`` already separates the
    divider heading from its subtitle and the 교회 소식 eyebrow from its title); no 인도자 / 다 같이
    labels are added, because ``content.py``'s wording is dumped from the church's deck, never
    composed.

    The question is **pinned** below the title and the answer hangs from the bar, rather than the
    three being centred as one composite — see ``LITURGY_QUESTION_GAP``. The air around the bar is
    ``LITURGY_RULE_GAP`` wherever the answer leaves room for it and compresses evenly where it
    does not, which is what the operator's own three slides do (91/80 on the shortest answer,
    46/46 on the longest). Only if compressing to nothing still will not fit does ``_scaled``
    shrink the type — with the church's wording it never has to, so every 문답 slide ships at the
    same 72pt as the recitation ones.
    """
    slide = _slide(background=NAVY)
    x, y, w, h = _liturgy_body_rect(slide, title)
    body = "\n".join(answer)
    q_run: rtf.Run = (question, LITURGY_QUESTION)
    q_y = y + LITURGY_QUESTION_GAP
    q_h = _wrapped_height([q_run], w, 1.0)
    # The gap that lands the answer exactly on the foot of the content rect, capped at the
    # nominal one — so a roomy slide keeps the operator's air and a full one gives it back.
    below = (y + h) - (q_y + q_h + LITURGY_RULE_H)
    fitted = (below - _wrapped_height([(body, LITURGY_BODY)], w, 1.0)) / 2
    gap = min(LITURGY_RULE_GAP, max(0.0, fitted))
    rule_y = q_y + q_h + gap
    a_y = rule_y + LITURGY_RULE_H + gap
    a_h = (y + h) - a_y
    el.text(slide, (x, q_y, w, q_h), rtf.document([q_run]), LITURGY_QUESTION, valign="top")
    _rule(slide, rule_y, width=LITURGY_RULE_W, height=LITURGY_RULE_H)
    el.text(
        slide,
        (x, a_y, w, a_h),
        rtf.document(_scaled([(body, LITURGY_BODY)], w, a_h)),
        LITURGY_BODY,
        valign="top",
    )
    return _front_to_back(slide)


def service_intro(part: str, sermon_title: str, ref: str, date: str) -> slide_pb2.Slide:
    """Opening plate: date, 「N부 예배를 시작합니다」, this week's sermon title + ref, the notice.

    The two services share one deck, so this is built once per ``content.SERVICE_PARTS`` entry
    (master slides 1–2). ``ref`` is bare, e.g. ``"창 1:1-5"``: master.key brackets it, and the
    operator took the brackets off restyling a draft — on a slide whose only other line *is* the
    sermon title, nothing needs setting apart (#178 review, round 3).

    Laid out in **canvas** coordinates rather than off the content rect, because this is the one
    plate the operator compares side by side with the Keynote deck: the boxes below are
    master.key slide 1's own (date 621,297 · heading 169,386 · title+ref 222,634 · notice
    246,908), so the reading order and rhythm match line for line. Only the ground (navy instead
    of the bluegreen photo) and the type colors are ours.
    """
    slide = _slide(background=NAVY)
    _framed(slide, frame=False)
    _logo(slide, LOGO_TOP_RIGHT)
    el.text(slide, (240.0, 290.0, 1440.0, 110.0), rtf.plain(date, SERVICE_DATE), SERVICE_DATE)
    heading = f"{part} 예배를 시작합니다."
    el.text(
        slide, (140.0, 386.0, 1640.0, 250.0), rtf.plain(heading, SERVICE_HEADING), SERVICE_HEADING
    )
    runs: list[rtf.Run] = []
    if sermon_title:
        runs.append((sermon_title, SERVICE_TITLE))
    if ref:
        runs.append((("\n" if runs else "") + ref, SERVICE_REF))
    if runs:
        el.text(
            slide, (220.0, 634.0, 1480.0, 248.0), rtf.document(_scaled(runs, 1480.0, 248.0)),
            SERVICE_TITLE,
        )
    el.text(
        slide,
        (246.0, 900.0, 1448.0, 120.0),
        rtf.plain(content.OPENING_NOTICE, SERVICE_NOTICE),
        SERVICE_NOTICE,
    )
    return _front_to_back(slide)


def service_outro(part: str, date: str) -> slide_pb2.Slide:
    """Closing plate: date, 「N부 예배를 마칩니다」, and the church's closing line (master 167–168).

    Same canvas-coordinate treatment as ``service_intro`` — master.key slide 167 stacks the date
    and the heading in one box (57,312 1804×423) with the blessing under it (387,767).
    """
    slide = _slide(background=NAVY)
    _framed(slide, frame=False)
    style = replace(SERVICE_HEADING, size=105)
    el.text(
        slide,
        (60.0, 312.0, 1800.0, 423.0),
        rtf.document([(date + "\n", style), (f"{part} 예배를 마칩니다.", style)]),
        style,
    )
    _rule(slide, 742.0, width=90.0)
    el.text(
        slide,
        (390.0, 800.0, 1140.0, 170.0),
        rtf.plain(content.CLOSING_BLESSING, CLOSING_BLESSING),
        CLOSING_BLESSING,
    )
    return _front_to_back(slide)


def text_card(
    lines: list[str | tuple[str, str]], accent_lines: tuple[int, ...] = ()
) -> slide_pb2.Slide:
    """Centered fixed-wording card — 교회 표어, 환영, 폐회 안내.

    ``accent_lines`` indexes the lines to set wholly in gold (the 표어 line of the 환영 card);
    everything else is white. A line given as a ``(gold, white)`` pair splits mid-line instead —
    the 표어 needs it, where only the quoted motto is gold and the 「입니다.」 that closes the
    sentence is not (#178 review, round 3). One text element, so the block stays vertically
    centred as a whole, with the logo bottom-right as master.key slide 3 has it.
    """
    slide = _slide(background=NAVY)
    x, y, w, h = _framed(slide, frame=False)
    _logo(slide, LOGO_BOTTOM_RIGHT)
    runs: list[rtf.Run] = []
    for i, line in enumerate(lines):
        head = "\n" if i else ""
        if isinstance(line, tuple):
            runs += [(head + line[0], CARD_ACCENT), (line[1], CARD_BODY)]
        else:
            runs.append((head + line, CARD_ACCENT if i in accent_lines else CARD_BODY))
    # 160pt of the content rect is given up to the logo's corner, but the card is centred in
    # what is left of the *canvas*, not pushed up by it — the block reading high is what the
    # operator's own ProPresenter re-layout corrected (#178 review, round 3).
    box = (x, y + 80.0, w, h - 160.0)
    el.text(slide, box, rtf.document(_scaled(runs, w, box[3])), CARD_BODY)
    return _front_to_back(slide)


def closing_note(lines: list[str], farewell: str) -> slide_pb2.Slide:
    """폐회 안내 — the instruction the congregation acts on, then the farewell (master 169, #249).

    These are not two halves of one message. ``lines`` tells people what to do when the service
    ends; ``farewell`` is a courtesy. Set as one flat block on a ``text_card`` they read as three
    equal instructions, which is what the first `.pro` deck did — Keynote's own slide already
    sets the farewell smaller. So the instruction keeps the full ``CARD_BODY``, a gold ``_rule``
    closes it, and the farewell sits under the rule in ``CARD_FAREWELL``.

    The assembly is centred as a whole in the card box, so the rule lands wherever the message
    ends rather than at a fixed height — the message is fixed wording, but a re-worded card
    should not have to re-tune a constant. Every box is sized from ``_wrapped_height``, which is
    what ``scripts/audit_pro_layout.py`` measures against.
    """
    slide = _slide(background=NAVY)
    x, y, w, h = _framed(slide, frame=False)
    _logo(slide, LOGO_BOTTOM_RIGHT)
    box = (x, y + 80.0, w, h - 160.0)  # the logo's corner, as text_card gives it up
    runs: list[rtf.Run] = [(("\n" if i else "") + line, CARD_BODY) for i, line in enumerate(lines)]
    message_h = _wrapped_height(runs, w, 1.0)
    farewell_h = _wrapped_height([(farewell, CARD_FAREWELL)], w, 1.0)
    tail_h = 2 * CLOSING_RULE_GAP + LITURGY_RULE_H + farewell_h
    top = box[1] + max((box[3] - message_h - tail_h) / 2, 0.0)
    el.text(slide, (x, top, w, message_h), rtf.document(runs), CARD_BODY, valign="top")
    rule_y = top + message_h + CLOSING_RULE_GAP
    _rule(slide, rule_y, width=90.0, height=LITURGY_RULE_H)
    el.text(
        slide,
        (x, rule_y + LITURGY_RULE_H + CLOSING_RULE_GAP, w, farewell_h),
        rtf.plain(farewell, CARD_FAREWELL),
        CARD_FAREWELL,
        valign="top",
    )
    return _front_to_back(slide)


def logo_plate() -> slide_pb2.Slide:
    """The church logo alone, centred — the deck's last plate but one (master slide 170, #249).

    Keynote closes on this and then the church photo, and the operator holds on whichever suits
    the room after the service. Nothing but the logo is on it: the ``_framed`` tint (no outline,
    like the other plates) over the backdrop, and the artwork at its own aspect in ``LOGO_CENTER``.
    """
    slide = _slide(background=NAVY)
    _framed(slide, frame=False)
    _logo(slide, LOGO_CENTER)
    return _front_to_back(slide)


def blank_green() -> slide_pb2.Slide:
    """Blank chroma-green separator — the cue that leaves the live camera alone.

    One trails every song: ProPresenter's Clear button blanks to *black*, dropping the chroma
    overlay entirely, so the operator arrows onto a real green cue instead of reaching for it.
    """
    return _slide(background=CHROMA_GREEN)


def image(path: str) -> slide_pb2.Slide:
    """Full-bleed image slide — 봉헌 hymn PNG pages (#179) and band lead sheets."""
    slide = _slide()
    el.image(slide, (0.0, 0.0, *CANVAS), path)
    return slide


BUILDERS = {
    "worship_lyric_ko": worship_lyric_ko,
    "worship_lyric_bilingual": worship_lyric_bilingual,
    "song_banner": song_banner,
    "verse_fullscreen": verse_fullscreen,
    "announcement": announcement,
    "section_divider": section_divider,
    "verse_divider": verse_divider,
    "sermon_title": sermon_title,
    "keyed_label": keyed_label,
    "liturgy": liturgy,
    "liturgy_responsive": liturgy_responsive,
    "service_intro": service_intro,
    "service_outro": service_outro,
    "text_card": text_card,
    "closing_note": closing_note,
    "logo_plate": logo_plate,
    "blank_green": blank_green,
    "image": image,
}

# Section band colors for the ProPresenter group headers (cosmetic, operator-facing).
GROUP_COLORS: dict[str, tuple[int, int, int]] = {
    "예배 시작": (0x6B, 0x7A, 0x8E),
    "예배의 부름": (0x3B, 0x6E, 0xA5),
    "회개로의 초대": (0x7A, 0x6B, 0xA8),
    "죄사함의 선포": (0x7A, 0x6B, 0xA8),
    "찬양": (0x2E, 0x8B, 0x6B),
    "고백의 찬양": (0x2E, 0x8B, 0x6B),
    "사도신경": (0x7A, 0x6B, 0xA8),
    "성가대 찬양": (0xA8, 0x6B, 0x8E),
    "봉 헌": (0xA8, 0x8B, 0x4B),
    "환영 및 인사": (0x6B, 0x7A, 0x8E),
    "교회 소식": (0x6B, 0x7A, 0x8E),
    "합심 기도": (0x7A, 0x6B, 0xA8),
    "말씀": (0x3B, 0x6E, 0xA5),
    "파송의 노래": (0x2E, 0x8B, 0x6B),
    "축도": (0x7A, 0x6B, 0xA8),
    "주기도문": (0x7A, 0x6B, 0xA8),
    "예배 마침": (0x6B, 0x7A, 0x8E),
}


# One hue per song in the medley (#176 follow-up): the weekly deck is one flat list of group
# bars, so cycling the color is what lets the operator see where one song ends and the next
# begins. Cycles if a medley ever runs longer than the palette.
SONG_COLORS: tuple[tuple[int, int, int], ...] = (
    (0x2E, 0x8B, 0x6B),  # green
    (0x3B, 0x6E, 0xA5),  # blue
    (0xA8, 0x6B, 0x8E),  # mauve
    (0xA8, 0x8B, 0x4B),  # amber
)

# Slide-label colors for the operator-labeled song sections (#113). These tint the per-slide
# label (`Action.Label`), not a group — see design doc Decision 4. Keyed by the label with
# trailing digits stripped, so V1/V2 and B/B2 read alike; `간주` and the other Korean labels the
# review dropdown offers are matched verbatim.
SECTION_COLORS: dict[str, tuple[int, int, int]] = {
    "V": (0x3B, 0x6E, 0xA5),        # verse — blue
    "C": (0xA8, 0x4B, 0x4B),        # chorus — rose
    "PC": (0x3B, 0x8E, 0x8E),       # pre-chorus — teal
    "B": (0x7A, 0x6B, 0xA8),        # bridge — purple
    "TAG": (0xA8, 0x8B, 0x4B),      # amber
    "ENDING": (0xA8, 0x8B, 0x4B),
    "INTRO": (0x6B, 0x7A, 0x8E),    # slate
    "\uac04\uc8fc": (0x6B, 0x7A, 0x8E),
}


def section_color(label: str) -> tuple[int, int, int]:
    """The slide-label color for a song-section label; operator-typed customs fall back to slate."""
    key = label.strip().upper().rstrip("0123456789") or label.strip().upper()
    return SECTION_COLORS.get(key, SECTION_COLORS["INTRO"])
