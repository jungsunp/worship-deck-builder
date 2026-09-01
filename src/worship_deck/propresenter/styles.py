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
renders: the sample CSS left the strips loose around the text and touching each other. Selectable
presets and live restyling are Phase 5 (#222/#223) — which is exactly why these are plain
module constants rather than a binary.

Each ``STYLE_KEYS`` entry has a builder below returning a finished ``Slide``; the per-section
``build.fill_*`` functions (#175–#179) call them with weekly content.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

# isort: off
from . import pb  # noqa: F401 -- side effect: puts pb/ on sys.path for the bare *_pb2 imports

import slide_pb2

# isort: on
from worship_deck.bible import layout

from . import content, rtf
from . import elements as el

# The slide types the generator can produce. Each maps to one builder function below.
STYLE_KEYS = (
    "worship_lyric_ko",         # sung lyrics, lower-third, up to 2 Korean lines
    "worship_lyric_bilingual",  # 1 dominant KO line + 1 smaller EN line (needs a KO+EN source, #228)
    "song_banner",              # keyed lower-third song title (worship medley)
    "song_title",               # full-screen song / section title banner
    "verse_fullscreen",         # bilingual scripture body (개역한글 + ESV)
    "announcement",             # 교회소식 item (gold title + muted detail)
    "section_divider",          # section heading (예배의 부름 / 봉헌 / 교회 소식 …)
    "keyed_label",              # section heading keyed over the live camera (#234)
    "liturgy",                  # fixed-wording full-screen (사도신경 / 주기도문)
    "service_intro",            # N부 예배를 시작합니다 + sermon title / ref / date
    "service_outro",            # N부 예배를 마칩니다 + date
    "text_card",                # centered fixed-wording card (표어 / 환영 / 예배 준비 / 폐회)
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
# than a soft-alpha stroke (#192). Both are drawn at BRUSH_ASPECT, so they share the measured rects.
# `M1` is the shipped look — a skewed navy-gradient bar with a gold rule, chosen over every flat,
# gradient, scrim and repainted-stroke treatment in the bake-off. `A` is Keynote's own watercolour,
# kept only so the church group can compare the two in the #223 preset review.
KEYED_ART: dict[str, tuple[str, float]] = {
    "M1": (str(ASSET_DIR / "m1-angled-bar.png"), BRUSH_ASPECT),
    "A": (BRUSH, BRUSH_ASPECT),
}

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

TINT_RGBA = (*NAVY, 0.62)  # sits over the (future #224) background image
FRAME_FILL_RGBA = (0x0A, 0x14, 0x28, 0.35)
FRAME_STROKE_RGBA = (*INK, 0.32)
FRAME_STROKE_WIDTH = 1.5
FRAME_RADIUS = 0.01  # ProPresenter roundness is a fraction of the shorter side (~10px)

# Fonts. The #189 samples use Pretendard / Noto Sans KR, which are not installed on either
# Mac (they exist only as web fonts under data/style-samples/fonts/). Apple SD Gothic Neo
# ships with macOS, so it is the safe default; swapping is a one-line change once the church
# mini has the real face installed (#191/#197).
FONT_FAMILY = "Apple SD Gothic Neo"
FONT_BOLD = "AppleSDGothicNeo-Bold"
FONT_REGULAR = "AppleSDGothicNeo-Regular"

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
KEYED_LABEL_INSET = 0.10  # fraction of the container width kept clear at each end



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
ANNOUNCE_HEADING = Style(FONT_BOLD, 44, ACCENT, bold=True, tracking=8.0)
ANNOUNCE_TITLE = Style(FONT_BOLD, 76, ACCENT, bold=True, line_spacing=16.0, align="left")
ANNOUNCE_DETAIL = Style(FONT_REGULAR, 64, MUTED, line_spacing=20.0, align="left")
KEYED_LABEL = Style(FONT_BOLD, 70, bold=True, tracking=2.0)
DIVIDER_KO = Style(FONT_BOLD, 190, bold=True, tracking=12.0)
DIVIDER_SUB = Style(FONT_BOLD, 76, ACCENT, bold=True, tracking=2.0)
LITURGY_TITLE = Style(FONT_BOLD, 48, ACCENT, bold=True, tracking=12.0)
LITURGY_BODY = Style(FONT_BOLD, 72, bold=True, line_spacing=22.0)
SERVICE_HEADING = Style(FONT_BOLD, 138, bold=True, line_spacing=10.0)
SERVICE_NOTICE = Style(FONT_REGULAR, 37, MUTED, line_spacing=8.0)
SERVICE_DATE = Style(FONT_BOLD, 79, bold=True, tracking=2.0)
SERVICE_TITLE = Style(FONT_BOLD, 70, ACCENT, bold=True, line_spacing=12.0)
SERVICE_REF = Style(FONT_BOLD, 60, ACCENT, bold=True, line_spacing=12.0)
CLOSING_BLESSING = Style(FONT_REGULAR, 75)
NOTE = Style(FONT_REGULAR, 18, BLACK, align="left")  # per-slide notes pane, not on the canvas
CARD_BODY = Style(FONT_BOLD, 80, bold=True, line_spacing=26.0)
CARD_ACCENT = Style(FONT_BOLD, 80, ACCENT, bold=True, line_spacing=26.0)


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

    The sample's blurred-photo backdrop is *not* drawn here. ProPresenter's own
    ``backgroundEffect.backgroundBlur`` would have supplied it for free, but 21.4 renders it
    as a placeholder and crashes on selection (verified 2026-08-13), so the blur has to come
    from a pre-blurred background image — the #224 library, dropped in behind this tint.
    """
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
        char_w = layout.CHAR_W_KO if any("가" <= c <= "힣" for c in text) else layout.CHAR_W_EN
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
    return sum(s * layout.LINE_PITCH for s in lines) + lead * len(lines)


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


def _scaled(runs: list[rtf.Run], width: float, height: float) -> list[rtf.Run]:
    """``runs`` with every style shrunk by ``_fit_scale`` (a no-op when they already fit)."""
    scale = _fit_scale(runs, width, height)
    if scale == 1.0:
        return runs
    return [
        (text, replace(style, size=style.size * scale, line_spacing=style.line_spacing * scale))
        for text, style in runs
    ]


def _rule(slide: slide_pb2.Slide, y: float, width: float = 96.0, height: float = 3.0) -> None:
    """The gold hairline the samples put under headings and between KO and EN."""
    el.shape(slide, ((CANVAS[0] - width) / 2, y, width, height), fill=(*ACCENT, 0.9))


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
    changes text. ``song_title`` stays the full-screen plate for the sections that genuinely
    read as a title card (#178).
    """
    slide = _slide(background=CHROMA_GREEN)
    height = LYRIC_KO.size * 1.6 + 2 * LYRIC_STRIP_PAD[1]
    rect = (0.0, CANVAS[1] - LYRIC_ZONE_BOTTOM - height, CANVAS[0], height)
    element = el.text(slide, rect, rtf.plain(title, LYRIC_KO), LYRIC_KO)
    el.line_strip(element, (*BLACK, 1.0), pad=LYRIC_STRIP_PAD)
    return _front_to_back(slide)


def song_title(title: str, subtitle: str = "") -> slide_pb2.Slide:
    """Full-screen song / section title plate (고백의 찬양, 성가대 with its composer credit).

    The worship medley uses ``song_banner`` instead — a title over the band shot, not a plate
    that replaces it.
    """
    slide = _slide(background=NAVY)
    content = _framed(slide)
    runs: list[rtf.Run] = [(title, TITLE)]
    if subtitle:
        runs.append(("\n" + subtitle, DIVIDER_SUB))
    el.text(slide, content, rtf.document(_scaled(runs, content[2], content[3])), TITLE)
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
    ko_label_h = layout.line_height(VERSE_LABEL.size)
    en_label_h = layout.line_height(VERSE_EN_LABEL.size)
    ko_body_h = VERSE_KO_LINES * (VERSE_KO.size * layout.LINE_PITCH + VERSE_KO.line_spacing)
    en_body_h = VERSE_EN_LINES * (VERSE_EN.size * layout.LINE_PITCH + VERSE_EN.line_spacing)

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


def announcement(heading: str, blocks: list[str]) -> slide_pb2.Slide:
    """교회소식. Each block is one ``"N. title\\n\\ndetail lines"`` item as ServiceData stores it —
    gold title, muted detail. The samples show several per slide; #178 decides the packing."""
    slide = _slide(background=NAVY)
    x, y, w, h = _framed(slide)
    # The heading is a small gold eyebrow, not a plate title: master.key gives each item slide
    # the whole canvas at 80pt (slides 123–131) and announces the section once, on its divider.
    el.text(slide, (x, y, w, 56.0), rtf.plain(heading, ANNOUNCE_HEADING), ANNOUNCE_HEADING)
    _rule(slide, y + 78.0)

    runs: list[rtf.Run] = []
    for i, block in enumerate(blocks):
        title, _, detail = block.partition("\n\n")
        runs.append((("\n\n" if i else "") + title + "\n", ANNOUNCE_TITLE))
        if detail:
            runs.append((detail, ANNOUNCE_DETAIL))
    if runs:
        top = y + 124.0
        box = (x, top, w, h - (top - y))
        el.text(slide, box, rtf.document(_scaled(runs, w, box[3])), ANNOUNCE_TITLE, valign="top")
    return _front_to_back(slide)


def section_divider(heading: str, subtitle: str = "") -> slide_pb2.Slide:
    """Section heading slide (예배의 부름 / 봉 헌 / 교회 소식 …) with the gold rule and subtitle.

    The subtitle is bare — the week's song title or scripture reference, no brackets. master.key
    writes ``[ 믿음으로 우리는 ]``; the operator dropped the brackets across the divider slides
    restyling a draft, since the gold rule above already separates it (#178 review, round 3).
    """
    slide = _slide(background=NAVY)
    x, y, w, h = _framed(slide)
    el.text(
        slide, (x, y, w, h * 0.62), rtf.plain(heading, DIVIDER_KO), DIVIDER_KO, valign="bottom"
    )
    _rule(slide, y + h * 0.62 + 40.0, width=90.0)
    if subtitle:
        el.text(
            slide,
            (x, y + h * 0.62 + 96.0, w, 140.0),
            rtf.plain(subtitle, DIVIDER_SUB),
            DIVIDER_SUB,
            valign="top",
        )
    return _front_to_back(slide)


def keyed_label(heading: str, placement: str = "top", variant: str = "M1") -> slide_pb2.Slide:
    """Section heading keyed over the live camera (회개로의 초대 / 죄사함의 선포 / 합심 기도, #234).

    These sections *annotate* the shot rather than replace it, so unlike ``section_divider`` the
    slide is chroma-green backed and carries only a small label — an unbacked slide renders black
    and covers the camera instead of keying (#192), the same reason the sung-lyric styles are
    backed. The plate is a PNG rather than drawn shapes because the #234 bake-off settled it: the
    operator preferred artwork to every flat, gradient and scrim treatment tried against it.

    ``variant`` picks the plate from ``KEYED_ART`` — ``M1`` is the shipped look; ``A`` is kept so
    the church group can see it beside M1 in the #223 preset review.

    Both placements exist, and both are emitted per section: Keynote carries one per service part,
    but in ProPresenter the operator holds on a cue and chooses by where the label can sit without
    covering the live shot.
    """
    slide = _slide(background=CHROMA_GREEN)
    (x, y, w, h), size = KEYED_LABEL_PLACEMENTS[placement]
    style = replace(KEYED_LABEL, size=size)
    inset = w * KEYED_LABEL_INSET
    el.image(slide, (x, y, w, h), KEYED_ART[variant][0], fill_frame=False)
    element = el.text(
        slide,
        (x + inset, y, w - 2 * inset, h),
        rtf.document(_scaled([(heading, style)], w - 2 * inset, h)),
        style,
    )
    el.shadow(element)
    return _front_to_back(slide)


def liturgy(title: str, lines: list[str]) -> slide_pb2.Slide:
    """Fixed-wording full-screen liturgy (사도신경 / 주기도문) — gold spaced title over the body."""
    slide = _slide(background=NAVY)
    x, y, w, h = _framed(slide)
    el.text(slide, (x, y, w, 60.0), rtf.plain(title, LITURGY_TITLE), LITURGY_TITLE)
    body: list[rtf.Run] = [("\n".join(lines), LITURGY_BODY)]
    el.text(
        slide,
        (x, y + 110.0, w, h - 110.0),
        rtf.document(_scaled(body, w, h - 110.0)),
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
    "song_title": song_title,
    "verse_fullscreen": verse_fullscreen,
    "announcement": announcement,
    "section_divider": section_divider,
    "keyed_label": keyed_label,
    "liturgy": liturgy,
    "service_intro": service_intro,
    "service_outro": service_outro,
    "text_card": text_card,
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
