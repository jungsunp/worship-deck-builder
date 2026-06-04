"""Fetch verse text for a reference in 개역한글 (Korean) and ESV (English).

The bulletin gives only references (e.g. "시 133:1-3", "눅 22:14-24"); the slides need
the full text. Both sources must be free (no payment):
  - ESV:    free ESV API (api.esv.org), non-commercial use.
  - 개역한글: bundled local dataset (verify license; internal church use).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from worship_deck.bible.esv import _ref_to_query, fetch_esv
from worship_deck.bible.kkrv import fetch_korean
from worship_deck.bible.ref import parse_ref


@dataclass
class Passage:
    reference: str
    korean: str   # 개역한글
    english: str  # ESV


def lookup(reference: str) -> Passage:
    """Resolve a Korean-style reference to 개역한글 + ESV text."""
    ref = parse_ref(reference)
    return Passage(
        reference=reference,
        korean=fetch_korean(ref),
        english=fetch_esv(ref),
    )


@dataclass
class Verse:
    number: int
    korean: str    # 개역한글, no number prefix
    english: str   # ESV, no number prefix


_ESV_VERSE_RE = re.compile(r"\[(\d+)\]\s*")


def _condense(text: str) -> str:
    """Collapse internal whitespace (incl. the ESV API's poetry line breaks + indentation)
    to single spaces, so a verse is one continuous string that Keynote can reflow to fit the
    box width. Without this, poetry passages render as many short lines and shrink tiny."""
    return re.sub(r"\s+", " ", text).strip()


def _split_esv_verses(text: str) -> dict[int, str]:
    """Parse ESV text like '[14] foo [15] bar' into {14: 'foo', 15: 'bar'}.

    ESV is fetched with include-verse-numbers=true, so each verse is prefixed with a
    bracketed number. Each verse is condensed to a single line. Text before the first marker
    (none, normally) is dropped.
    """
    out: dict[int, str] = {}
    parts = _ESV_VERSE_RE.split(text)
    # parts = [pre, num, body, num, body, ...]; iterate the (num, body) pairs.
    for i in range(1, len(parts) - 1, 2):
        out[int(parts[i])] = _condense(parts[i + 1])
    return out


def lookup_verses(reference: str) -> list[Verse]:
    """Resolve a reference to aligned per-verse 개역한글 + ESV text.

    The 개역한글 source returns verses newline-joined with no numbers; they are numbered
    from ref.verse_start, assuming a contiguous range (the common case for these slides).
    ESV verses are matched to those numbers by their bracketed marker. Both languages are
    condensed to single lines so Keynote can reflow them to the box width.
    """
    ref = parse_ref(reference)
    korean_lines = fetch_korean(ref).split("\n")
    english_by_num = _split_esv_verses(fetch_esv(ref))
    start = ref.verse_start if ref.verse_start is not None else 1
    return [
        Verse(number=start + i, korean=_condense(kr), english=english_by_num.get(start + i, ""))
        for i, kr in enumerate(korean_lines)
    ]


def verse_labels(reference: str) -> tuple[str, str]:
    """Build the (개역한글, ESV) header labels shown on a verse slide.

    e.g. "시 133:1-3" -> ("[시 133:1-3, 개역한글]", "[Psalms 133:1-3, ESV]").
    The Korean label keeps the raw reference; the English label uses the ESV book name.
    """
    kr_label = f"[{reference}, 개역한글]"
    en_label = f"[{_ref_to_query(parse_ref(reference))}, ESV]"
    return kr_label, en_label
