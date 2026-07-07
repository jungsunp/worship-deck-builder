"""Style-kit loader: the baked look for generated ``.pro`` decks (v3 migration, #171).

**Skeleton only (#171).** #172 implements the body.

ProPresenter bakes styling into each slide (font/color/size live on the text elements;
there is no runtime theme reference — see ``build.py``). So the generator can't "apply a
theme" at open time. Instead the designer authors a **style-kit ``.pro``** once in
ProPresenter (#170) — one exemplar slide per style preset, with the chosen Theme applied —
and the generator *clones* the matching prototype and swaps only its text (``rtf.py``).

Each prototype's editable text element carries a placeholder token (e.g. ``{{TEXT}}``,
``{{TEXT_KO}}``, ``{{TEXT_EN}}``) in its ``rtf_data`` so ``rtf.set_placeholder`` can find and
replace the run while preserving all baked RTF styling around it.

The style kit is **version-sensitive like the protos** (re-authored at #170, re-pinned at
#191 for church PP 18.4). Its path — the ``.pro`` binary — is #170's deliverable, not this
issue's; ``STYLE_KIT_PATH`` is the agreed interface point.
"""

from __future__ import annotations

from pathlib import Path

from . import pb  # noqa: F401 -- side effect: puts pb/ on sys.path for the bare *_pb2 imports

import slide_pb2

# The prototype presets the generator clones from. Each maps to exactly one exemplar slide in
# the style-kit .pro. Keep this list and the authored kit (#170) in agreement.
STYLE_KEYS = (
    "worship_lyric_ko",        # sung lyrics, lower-third, up to 2 Korean lines
    "worship_lyric_bilingual",  # 1 dominant KO line + 1 smaller EN line (Glossa/#177 lives here)
    "song_title",              # song / section title banner
    "verse_fullscreen",        # bilingual scripture body (개역한글 + ESV)
    "announcement",            # 교회소식 item (gold title + white detail)
    "section_divider",         # section heading (예배의 부름 / 봉헌 / 교회소식 …)
    "liturgy",                 # fixed-wording full-screen (사도신경 / 주기도문)
    "blank_green",             # blank chroma-green separator
    "image",                   # full-bleed image slide (hymn PNG pages, band lead sheets)
)

# Set by #170; a plain module-level path is the hand-off contract. Kept next to the version-
# pinned protos so it moves together at the #191 re-pin.
STYLE_KIT_PATH = Path(__file__).with_name("style_kit.pro")


def prototype(style_key: str) -> slide_pb2.Slide:
    """Return a fresh clone of the style-kit exemplar slide for ``style_key``.

    Loads (and caches) the style-kit ``.pro``, finds the exemplar cue tagged for ``style_key``,
    deep-copies its ``base_slide``, and assigns fresh element UUIDs so the returned slide is safe
    to mutate and append. Raises ``KeyError`` for an unknown key, ``FileNotFoundError`` if the kit
    is missing. #172 implements this.
    """
    raise NotImplementedError("#172: load style-kit .pro and index prototypes by style key")
