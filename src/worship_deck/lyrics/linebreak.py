"""Phrase-aware re-breaking of transcribed lyric lines (#126).

The worship/고백 lyric banners are fixed-width autoshrink boxes and ``chunk()`` groups
lines 2-per-slide with no notion of fit, so over-long transcribed lines render small and
cramped. ``rebreak()`` runs inside ``transcribe()`` — after the gasazip lookup, before
results are persisted for review — greedily splitting over-long lines at their spaces.
A local model used to pick musical-phrase boundaries here; it was dropped with the rest
of the Ollama path (#213) — an untimed model call on every assemble for a split the
operator can drag in review, and canonical gasazip lines rarely exceed the cap anyway. Repeated phrases/lines stay verbatim — the operator reads
slides against the sheet while labeling sections, and ``… X N`` marks read worse than the
repeat itself (2026-07-16 review).

Fit model (same glyph-advance model as keynote/build.py, #115): measured on master.key,
the worship (slide 8) and 고백 (slide 60) lyric banners are identical — on-canvas text
item 1763pt wide, base font 87pt — so one constant serves both. Full width holds
1763/(87*0.83) ≈ 24 Hangul chars, but full-width lines read congested (the 2026-06-07
deck's slide-8 defect line is exactly 24 chars; the template's own comfortable lines run
≤21), so the cap applies a 0.92 fill.
"""

from __future__ import annotations

_LYRIC_BOX_W = 1763  # pt — lyric banner text-item width (master.key slides 8 and 60)
_LYRIC_FONT = 87  # pt — its base font
_CHAR_W_KO = 0.83  # avg Hangul glyph advance / font — matches keynote/build.py (#115)
_FILL = 0.92  # headroom below the geometric maximum; see module docstring
MAX_CHARS = int(_LYRIC_BOX_W * _FILL / (_LYRIC_FONT * _CHAR_W_KO))  # 22


def _split_at_space(line: str, max_chars: int) -> list[str]:
    """Rule-based fallback: greedy split at spaces so each part fits ``max_chars``.

    A single overlong word stays whole and autoshrinks slightly.
    """
    rest = line.split()
    parts: list[str] = []
    while rest:
        cur = [rest.pop(0)]
        while rest and len(" ".join([*cur, rest[0]])) <= max_chars:
            cur.append(rest.pop(0))
        parts.append(" ".join(cur))
    return parts


def rebreak(lines: list[str], *, max_chars: int = MAX_CHARS) -> list[str]:
    """Split over-long lyric lines so each fits the banner.

    Blank lines (stanza breaks, the ``chunk()`` convention) pass through untouched, as do
    lines already within ``max_chars``. Pure and I/O-free.
    """
    out: list[str] = []
    for line in lines:
        cleaned = line.strip()
        if len(cleaned) > max_chars:
            out.extend(_split_at_space(cleaned, max_chars))
        else:
            out.append(cleaned)
    return out
