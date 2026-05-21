"""Fetch verse text for a reference in 개역한글 (Korean) and ESV (English).

The bulletin gives only references (e.g. "시 133:1-3", "눅 22:14-24"); the slides need
the full text. Both sources must be free (no payment):
  - ESV:    free ESV API (api.esv.org), non-commercial use.
  - 개역한글: bundled local dataset (verify license; internal church use).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Passage:
    reference: str
    korean: str   # 개역한글
    english: str  # ESV


def lookup(reference: str) -> Passage:
    """Resolve a Korean-style reference to 개역한글 + ESV text."""
    raise NotImplementedError
