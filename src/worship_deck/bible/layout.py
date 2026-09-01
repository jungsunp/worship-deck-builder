"""Verse-slide packing: how many verses fit one slide at a target font (#115).

Pure geometry — no Keynote, no ProPresenter, no I/O. Both builders lay a passage into a
fixed-size bilingual body box and must split it across slides when it overflows, so the model
lives here rather than in either one: ``keynote/build.py`` reads its box sizes off the open
template, ``propresenter/build.py`` derives them from the baked style constants, and both feed
the same chunker.

The ratios are calibrated against the operator-approved deck: slide 46 of the 2026-06-07 final
deck (눅 15:19-20 — KO 84pt = 6 wrapped lines filling the 544pt box; EN 59pt = 5 lines in 298pt)
and ``master.key`` slide 48 (시 133:1-3, the same 6/5-line fill at the same fonts).
"""

from __future__ import annotations

import math

from worship_deck.bible.verses import Verse

# The vertical advance CoreText gives one line, as a multiple of the font size, for Apple SD
# Gothic Neo (measured on macOS 26: 1.2024–1.2143 across 30–110pt, and identical for Bold vs
# Regular and Hangul vs Latin). A style's ``line_spacing`` is *extra* leading added on top of
# this — the first line never gets it, but the last line does: ProPresenter reserves the
# spacing after the final line, so an N-line block costs ``N × (LINE_PITCH × size +
# line_spacing)``. Anything laying text into a fixed
# ProPresenter box has to budget with this; ProPresenter draws a "text is too large for its
# text box" warning otherwise and clips the overflow (#178 review). The ``LINE_H_*`` ratios
# below are Keynote's own measured fill, which already folds in that app's box insets and
# autoshrink — they are not interchangeable with this.
LINE_PITCH = 1.21

LINE_H_KO = 1.07    # verse line height / font (544pt box ÷ 6 lines @84pt ⇒ ≤1.079)
LINE_H_EN = 1.00    # verse line height / font (298pt box ÷ 5 lines @59pt ⇒ ≤1.010)
CHAR_W_KO = 0.83    # avg glyph advance / font — Hangul 1.0 minus space/punct share
                    # (0.9 wrongly splits 시 133:1-3 onto 2 slides)
CHAR_W_EN = 0.44    # avg glyph advance / font — proportional Latin incl. spaces


def line_height(font: float) -> float:
    """The height a *single* line of ``font`` pt occupies.

    Not simply ``font × LINE_PITCH``: CoreText rounds each line up to a whole point, and the
    first line of a block gets a shade more than the pitch (its full ascent, with no leading
    borrowed from the line above) — 44pt measures 54, where the pitch alone predicts 53.2. The
    extra point covers both, which matters for the one-line boxes that hold a slide's labels.
    """
    return math.ceil(font * LINE_PITCH) + 1.0


def verse_lines(text: str, box_w: float, font: float, char_w: float) -> int:
    """How many wrapped lines `"N. " + text` takes in a box `box_w` wide at `font` pt."""
    chars_per_line = max(1, int(box_w / (font * char_w)))
    return max(1, math.ceil(len(text) / chars_per_line))


def fit_lines(box_h: float, font: float, line_h: float) -> int:
    """How many lines of `font` pt (at `line_h` × font per line) fit in a box `box_h` tall."""
    return max(1, int(box_h / (font * line_h)))


def chunk_verses(
    verses: list[Verse],
    *,
    ko_box: tuple[float, float],
    en_box: tuple[float, float],
    ko_font: float,
    en_font: float,
    ko_line_h: float = LINE_H_KO,
    en_line_h: float = LINE_H_EN,
) -> list[list[Verse]]:
    """Group consecutive verses so each slide fills well at the target font (#115).

    For each body box (width, available height), estimate how many wrapped lines fit at the
    target font; a verse starts a new slide when adding it would exceed EITHER language's
    line budget (verses don't share a line). Short verses pack >2 per slide, long ones spread
    out — consistent density everywhere. A verse that overflows on its own still gets its own
    slide (the caller shrinks its font, or lets the app autoshrink).

    ``*_line_h`` default to the Keynote deck's measured ratios; the ProPresenter builder passes
    its own, because its styles carry an explicit extra leading that widens the line pitch well
    past what the glyphs alone need.
    """
    ko_w, ko_h = ko_box
    en_w, en_h = en_box
    ko_budget = fit_lines(ko_h, ko_font, ko_line_h)
    en_budget = fit_lines(en_h, en_font, en_line_h)

    chunks: list[list[Verse]] = []
    current: list[Verse] = []
    ko_used = en_used = 0
    for v in verses:
        ko_need = verse_lines(f"{v.number}. {v.korean}", ko_w, ko_font, CHAR_W_KO)
        en_need = verse_lines(f"{v.number}. {v.english}", en_w, en_font, CHAR_W_EN)
        if current and (ko_used + ko_need > ko_budget or en_used + en_need > en_budget):
            chunks.append(current)
            current, ko_used, en_used = [], 0, 0
        current.append(v)
        ko_used += ko_need
        en_used += en_need
    if current:
        chunks.append(current)
    return chunks
