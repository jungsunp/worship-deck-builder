"""Baked slide styling for generated ``.pro`` decks (v3 migration, #172).

ProPresenter has **no runtime theme reference**: ``PresentationSlide`` carries no theme
field and ``Action.SlideType`` has ``reserved "template"``, so font/color/size live on each
element. #170 closed on the consequence — there is no authored style-kit ``.pro`` to clone
from; the generator bakes the look per slide from the values here.

Those values are the interim pick recorded on #168: lyric **Option A (검정 스트립)** and
full-screen **Option 3 (네이비 프레임)**. ``scripts/render_style_samples.py`` holds the same
numbers as HTML/CSS and ``docs/style-samples/*.png`` is the rendering to match. Selectable
presets and live restyling are Phase 5 (#222/#223) — which is exactly why these are plain
module constants rather than a binary.

Each ``STYLE_KEYS`` entry has a builder below returning a finished ``Slide``; the per-section
``build.fill_*`` functions (#175–#179) call them with weekly content.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

# isort: off
from . import pb  # noqa: F401 -- side effect: puts pb/ on sys.path for the bare *_pb2 imports

import slide_pb2

# isort: on
from . import elements as el
from . import rtf

# The slide types the generator can produce. Each maps to one builder function below.
STYLE_KEYS = (
    "worship_lyric_ko",         # sung lyrics, lower-third, up to 2 Korean lines
    "worship_lyric_bilingual",  # 1 dominant KO line + 1 smaller EN line (Glossa/#177 lives here)
    "song_title",               # song / section title banner
    "verse_fullscreen",         # bilingual scripture body (개역한글 + ESV)
    "announcement",             # 교회소식 item (gold title + muted detail)
    "section_divider",          # section heading (예배의 부름 / 봉헌 / 교회 소식 …)
    "liturgy",                  # fixed-wording full-screen (사도신경 / 주기도문)
    "blank_green",              # blank chroma-green separator
    "image",                    # full-bleed image slide (hymn PNG pages, band lead sheets)
)

CANVAS = (1920.0, 1080.0)

# ── Palette (Option 3 네이비 프레임) ────────────────────────────────────────────
# RGB triples; RTF has no alpha, so the sample's translucent inks are pre-blended over the
# navy ground. Element fills (which *do* have alpha) keep their alpha as the 4th component.
NAVY = (0x10, 0x20, 0x3B)
ACCENT = (0xFF, 0xD4, 0x47)  # gold: verse numbers, rules, labels
INK = (0xFF, 0xFF, 0xFF)
MUTED = (0xBC, 0xC0, 0xC7)  # white .72 over navy — ESV body, announcement detail
BLACK = (0x00, 0x00, 0x00)  # Option A lyric strips
CHROMA_GREEN = (0x00, 0xFF, 0x00)  # keyed out by the ATEM (#192); see blank_green()

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
FRAME_INSET = (140.0, 96.0)  # x, y — the 네이비 프레임 box
LYRIC_ZONE_BOTTOM = 72.0     # Option A: distance from the bottom edge
LYRIC_STRIP_PAD = (34.0, 12.0)  # x, y padding of the black strip around each line
CONTENT_INSET = (100.0, 64.0)  # padding inside the frame box


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


# Per-section type scale, matching the sample PNGs.
LYRIC_KO = Style(FONT_BOLD, 68, bold=True, line_spacing=10.0)
LYRIC_EN = Style(FONT_REGULAR, 34, MUTED, tracking=1.5, line_spacing=10.0)
TITLE = Style(FONT_BOLD, 72, bold=True, tracking=2.0, line_spacing=14.0)
VERSE_LABEL = Style(FONT_BOLD, 31, ACCENT, bold=True, line_spacing=42.0, align="left")
VERSE_NUMBER = Style(FONT_BOLD, 26, ACCENT, bold=True, align="left")
VERSE_KO = Style(FONT_BOLD, 47, line_spacing=31.0, align="left")
VERSE_EN_LABEL = Style(FONT_REGULAR, 25, ACCENT, line_spacing=20.0, align="left")
VERSE_EN = Style(FONT_REGULAR, 31, MUTED, line_spacing=19.0, align="left")
ANNOUNCE_HEADING = Style(FONT_BOLD, 58, bold=True, tracking=8.0)
ANNOUNCE_TITLE = Style(FONT_BOLD, 41, ACCENT, bold=True, line_spacing=10.0, align="left")
ANNOUNCE_DETAIL = Style(FONT_REGULAR, 33, MUTED, line_spacing=15.0, align="left")
DIVIDER_KO = Style(FONT_BOLD, 136, bold=True, tracking=30.0)
DIVIDER_SUB = Style(FONT_REGULAR, 37, MUTED, tracking=2.0)
LITURGY_TITLE = Style(FONT_BOLD, 38, ACCENT, bold=True, tracking=12.0)
LITURGY_BODY = Style(FONT_REGULAR, 46, line_spacing=38.0)


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


def _framed(slide: slide_pb2.Slide) -> tuple[float, float, float, float]:
    """Draw the Option 3 backdrop — navy tint + frame box — and return the content rect.

    The sample's blurred-photo backdrop is *not* drawn here. ProPresenter's own
    ``backgroundEffect.backgroundBlur`` would have supplied it for free, but 21.4 renders it
    as a placeholder and crashes on selection (verified 2026-08-13), so the blur has to come
    from a pre-blurred background image — the #224 library, dropped in behind this tint.
    """
    full = (0.0, 0.0, *CANVAS)
    el.shape(slide, full, fill=TINT_RGBA)
    x, y = FRAME_INSET
    frame = (x, y, CANVAS[0] - 2 * x, CANVAS[1] - 2 * y)
    el.shape(
        slide,
        frame,
        fill=FRAME_FILL_RGBA,
        stroke=(FRAME_STROKE_RGBA, FRAME_STROKE_WIDTH),
        roundness=FRAME_RADIUS,
    )
    px, py = CONTENT_INSET
    return (frame[0] + px, frame[1] + py, frame[2] - 2 * px, frame[3] - 2 * py)


def _rule(slide: slide_pb2.Slide, y: float, width: float = 96.0, height: float = 3.0) -> None:
    """The gold hairline the samples put under headings and between KO and EN."""
    el.shape(slide, ((CANVAS[0] - width) / 2, y, width, height), fill=(*ACCENT, 0.9))


def worship_lyric_ko(lines: list[str]) -> slide_pb2.Slide:
    """Option A lower-third: bold white lyrics on per-line black strips, over live camera."""
    slide = _slide()
    height = LYRIC_KO.size * 1.6 * len(lines) + 2 * LYRIC_STRIP_PAD[1]
    rect = (0.0, CANVAS[1] - LYRIC_ZONE_BOTTOM - height, CANVAS[0], height)
    element = el.text(slide, rect, rtf.plain("\n".join(lines), LYRIC_KO), LYRIC_KO)
    el.line_strip(element, (*BLACK, 1.0), pad=LYRIC_STRIP_PAD)
    return _front_to_back(slide)


def worship_lyric_bilingual(korean: str, english: str) -> slide_pb2.Slide:
    """Option A lower-third with a smaller English line under the Korean (Glossa slot, #177)."""
    slide = _slide()
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


def song_title(title: str, subtitle: str = "") -> slide_pb2.Slide:
    """Song / section title banner (worship medley, 고백의 찬양, 성가대 with its composer credit)."""
    slide = _slide(background=NAVY)
    content = _framed(slide)
    runs: list[rtf.Run] = [(title, TITLE)]
    if subtitle:
        runs.append(("\n" + subtitle, DIVIDER_SUB))
    el.text(slide, content, rtf.document(runs), TITLE)
    return _front_to_back(slide)


def verse_fullscreen(
    ko_label: str,
    ko_verses: list[tuple[int, str]],
    en_label: str,
    en_verses: list[tuple[int, str]],
) -> slide_pb2.Slide:
    """Bilingual scripture: 개역한글 above, a gold rule, then ESV — verse numbers in gold."""
    slide = _slide(background=NAVY)
    x, y, w, h = _framed(slide)

    ko_runs: list[rtf.Run] = [(ko_label + "\n", VERSE_LABEL)]
    for i, (number, text) in enumerate(ko_verses):
        ko_runs += [(("\n" if i else "") + f"{number} ", VERSE_NUMBER), (text, VERSE_KO)]
    en_runs: list[rtf.Run] = [(en_label + "\n", VERSE_EN_LABEL)]
    for i, (number, text) in enumerate(en_verses):
        en_runs += [
            (("\n" if i else "") + f"{number} ", replace(VERSE_NUMBER, size=20)),
            (text, VERSE_EN),
        ]

    ko_h = h * 0.56
    el.text(slide, (x, y, w, ko_h), rtf.document(ko_runs), VERSE_LABEL, valign="top")
    _rule(slide, y + ko_h + 12.0, width=84.0, height=1.0)
    el.text(
        slide,
        (x, y + ko_h + 58.0, w, h - ko_h - 58.0),
        rtf.document(en_runs),
        VERSE_EN_LABEL,
        valign="top",
    )
    return _front_to_back(slide)


def announcement(heading: str, blocks: list[str]) -> slide_pb2.Slide:
    """교회소식. Each block is one ``"N. title\\n\\ndetail lines"`` item as ServiceData stores it —
    gold title, muted detail. The samples show several per slide; #178 decides the packing."""
    slide = _slide(background=NAVY)
    x, y, w, h = _framed(slide)
    el.text(slide, (x, y, w, 90.0), rtf.plain(heading, ANNOUNCE_HEADING), ANNOUNCE_HEADING)
    _rule(slide, y + 118.0)

    runs: list[rtf.Run] = []
    for i, block in enumerate(blocks):
        title, _, detail = block.partition("\n\n")
        runs.append((("\n\n" if i else "") + title + "\n", ANNOUNCE_TITLE))
        if detail:
            runs.append((detail, ANNOUNCE_DETAIL))
    if runs:
        top = y + 176.0
        el.text(slide, (x, top, w, h - (top - y)), rtf.document(runs), ANNOUNCE_TITLE, valign="top")
    return _front_to_back(slide)


def section_divider(heading: str, subtitle: str = "") -> slide_pb2.Slide:
    """Section heading slide (예배의 부름 / 봉 헌 / 교회 소식 …) with the gold rule and subtitle."""
    slide = _slide(background=NAVY)
    x, y, w, h = _framed(slide)
    el.text(slide, (x, y, w, h * 0.6), rtf.plain(heading, DIVIDER_KO), DIVIDER_KO, valign="bottom")
    _rule(slide, y + h * 0.6 + 46.0, width=90.0)
    if subtitle:
        el.text(
            slide,
            (x, y + h * 0.6 + 110.0, w, 80.0),
            rtf.plain(subtitle, DIVIDER_SUB),
            DIVIDER_SUB,
            valign="top",
        )
    return _front_to_back(slide)


def liturgy(title: str, lines: list[str]) -> slide_pb2.Slide:
    """Fixed-wording full-screen liturgy (사도신경 / 주기도문) — gold spaced title over the body."""
    slide = _slide(background=NAVY)
    x, y, w, h = _framed(slide)
    el.text(slide, (x, y, w, 70.0), rtf.plain(title, LITURGY_TITLE), LITURGY_TITLE)
    el.text(
        slide,
        (x, y + 128.0, w, h - 128.0),
        rtf.plain("\n".join(lines), LITURGY_BODY),
        LITURGY_BODY,
        valign="top",
    )
    return _front_to_back(slide)


def blank_green() -> slide_pb2.Slide:
    """Blank chroma-green separator. The ATEM keys this green out (#192); the exact shade must
    be matched to the church's key settings when the generator is wired up (#180)."""
    return _slide(background=CHROMA_GREEN)


def image(path: str) -> slide_pb2.Slide:
    """Full-bleed image slide — 봉헌 hymn PNG pages (#179) and band lead sheets."""
    slide = _slide()
    el.image(slide, (0.0, 0.0, *CANVAS), path)
    return slide


BUILDERS = {
    "worship_lyric_ko": worship_lyric_ko,
    "worship_lyric_bilingual": worship_lyric_bilingual,
    "song_title": song_title,
    "verse_fullscreen": verse_fullscreen,
    "announcement": announcement,
    "section_divider": section_divider,
    "liturgy": liturgy,
    "blank_green": blank_green,
    "image": image,
}

# Section band colors for the ProPresenter group headers (cosmetic, operator-facing).
GROUP_COLORS: dict[str, tuple[int, int, int]] = {
    "예배의 부름": (0x3B, 0x6E, 0xA5),
    "찬양": (0x2E, 0x8B, 0x6B),
    "고백의 찬양": (0x2E, 0x8B, 0x6B),
    "사도신경": (0x7A, 0x6B, 0xA8),
    "성가대 찬양": (0xA8, 0x6B, 0x8E),
    "봉 헌": (0xA8, 0x8B, 0x4B),
    "교회 소식": (0x6B, 0x7A, 0x8E),
    "말씀": (0x3B, 0x6E, 0xA5),
    "주기도문": (0x7A, 0x6B, 0xA8),
}
