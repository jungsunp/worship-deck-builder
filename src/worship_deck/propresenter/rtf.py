"""RTF construction for ProPresenter slide text (v3 migration, #172).

A ProPresenter text element stores its visible text as ``rtf_data`` — Cocoa RTF bytes that
carry both the characters *and* the styling (font table, color table, paragraph, run
attributes). Because ProPresenter has no runtime theme reference (see ``build.py``), this
module *builds* those bytes from ``styles.Style`` values rather than substituting into an
authored prototype.

The emitted shape is copied verbatim from real PP 21.4 documents
(``~/Documents/ProPresenter/Libraries/Default/CMG - *.pro``)::

    {\\rtf1\\ansi\\ansicpg1252\\cocoartf2870
    \\cocoatextscaling0\\cocoaplatform0{\\fonttbl\\f0\\fnil\\fcharset0 CMGSans-Regular;}
    {\\colortbl;\\red255\\green255\\blue255;}
    {\\*\\expandedcolortbl;;\\csgenericrgb\\c100000\\c100000\\c100000;}
    \\pard\\slleading200\\pardirnatural\\qc\\partightenfactor0

    \\f0\\b\\fs120 \\cf1 He is here, our King is here\\
    No more sorrow and no more fear}

Three details are load-bearing:

* ``\\fsN`` is the point size **doubled** (60pt -> ``\\fs120``).
* A line break *inside* a slide is a backslash followed by LF — not ``\\par``, not ``\\line``.
* Non-ASCII is ``\\uc0\\uN `` (trailing space terminates the number), and RTF's ``\\u`` takes a
  **signed 16-bit** value, so Hangul (U+AC00–U+D7A3 = 44032–55203) must wrap negative.
  That wrap is the whole reason this module exists — a raw UTF-8 byte replace corrupts it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # styles imports this module, so keep the dependency one-way at runtime
    from .styles import Style

_HEADER = (
    "{\\rtf1\\ansi\\ansicpg1252\\cocoartf2870\n"
    "\\cocoatextscaling0\\cocoaplatform0"
)
_ALIGN_CONTROL = {"left": "\\ql", "center": "\\qc", "right": "\\qr"}

# One run of text and the style it is drawn in. A slide's text element is a list of these:
# the gold verse number then the white verse body, the gold announcement title then the
# muted detail lines, and so on.
Run = tuple[str, "Style"]


def escape(text: str) -> str:
    """Escape ``text`` for an RTF run.

    ``\\``, ``{`` and ``}`` are escaped; ``\\n`` becomes an in-slide line break; every
    non-ASCII code point becomes ``\\uN `` with RTF's signed-16-bit wrap.
    """
    out: list[str] = []
    for ch in text:
        cp = ord(ch)
        if ch in "\\{}":
            out.append("\\" + ch)
        elif ch == "\n":
            out.append("\\\n")
        elif cp < 128:
            out.append(ch)
        else:
            out.append(f"\\u{cp - 65536 if cp > 32767 else cp} ")
    return "".join(out)


def document(runs: Sequence[Run]) -> bytes:
    """Build the ``rtf_data`` bytes for a text element made of ``runs``.

    Paragraph settings (alignment, line spacing) come from the first run's style; per-run
    styles supply the font, size, weight, color and tracking.
    """
    if not runs:
        raise ValueError("at least one run is required")

    fonts: list[tuple[str, str]] = []  # (PostScript name, family)
    colors: list[tuple[int, int, int]] = []
    for _, style in runs:
        if (style.font, style.family) not in fonts:
            fonts.append((style.font, style.family))
        if style.rgb not in colors:
            colors.append(style.rgb)

    font_tbl = "".join(
        f"\\f{i}\\fnil\\fcharset0 {name};" for i, (name, _) in enumerate(fonts)
    )
    # Index 0 of the color table is a reserved blank slot, so the first usable color is \cf1.
    color_tbl = "".join(f"\\red{r}\\green{g}\\blue{b};" for r, g, b in colors)
    expanded = "".join(
        f"\\csgenericrgb\\c{round(r / 255 * 100000)}"
        f"\\c{round(g / 255 * 100000)}\\c{round(b / 255 * 100000)};"
        for r, g, b in colors
    )

    # \slleading is in twips (1/20 pt), matching PP's own output: line_spacing 15.0 -> 300.
    lead = runs[0][1]
    paragraph = (
        f"\\pard\\slleading{round(lead.line_spacing * 20)}\\pardirnatural"
        f"{_ALIGN_CONTROL[lead.align]}\\partightenfactor0"
    )

    body: list[str] = []
    for text, style in runs:
        prefix = (
            f"\\f{fonts.index((style.font, style.family))}"
            f"\\b{'' if style.bold else '0'}"
            f"\\fs{round(style.size * 2)} "
            f"\\cf{colors.index(style.rgb) + 1} "
        )
        if style.tracking:
            prefix += f"\\expnd{round(style.tracking * 4)}\\expndtw{round(style.tracking * 20)} "
        body.append(prefix + "\\uc0 " + escape(text))

    return (
        f"{_HEADER}{{\\fonttbl{font_tbl}}}\n"
        f"{{\\colortbl;{color_tbl}}}\n"
        f"{{\\*\\expandedcolortbl;{expanded}}}\n"
        f"{paragraph}\n\n"
        f"{''.join(body)}}}"
    ).encode()


def plain(text: str, style: Style) -> bytes:
    """``document`` for the common single-style case."""
    return document([(text, style)])
