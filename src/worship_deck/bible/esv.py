"""ESV API client: fetch passage text for a parsed BibleRef.

API: https://api.esv.org/v3/passage/text/ (free, non-commercial)
Key: ESV_API_KEY environment variable.
"""

from __future__ import annotations

import os

from worship_deck.bible.ref import BibleRef


def _ref_to_query(ref: BibleRef) -> str:
    """Build an ESV API query string from a BibleRef, e.g. 'Luke 22:14-24'."""
    if ref.verse_start is None:
        return f"{ref.book} {ref.chapter}"
    if ref.verse_end is None:
        return f"{ref.book} {ref.chapter}:{ref.verse_start}"
    return f"{ref.book} {ref.chapter}:{ref.verse_start}-{ref.verse_end}"


def fetch_esv(ref: BibleRef) -> str:
    """Return ESV passage text for *ref*, stripped of leading/trailing whitespace.

    Raises:
        RuntimeError: if ESV_API_KEY is not set.
        httpx.HTTPStatusError: on non-2xx responses.
    """
    api_key = os.environ.get("ESV_API_KEY")
    if not api_key:
        raise RuntimeError("ESV_API_KEY environment variable is not set")

    import httpx

    response = httpx.get(
        "https://api.esv.org/v3/passage/text/",
        params={
            "q": _ref_to_query(ref),
            "include-headings": "false",
            "include-footnotes": "false",
            "include-verse-numbers": "true",
            "include-short-copyright": "false",
            "include-passage-references": "false",
        },
        headers={"Authorization": f"Token {api_key}"},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()["passages"][0].strip()
