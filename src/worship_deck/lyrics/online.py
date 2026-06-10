"""Canonical worship-song lyrics from gasazip.com, keyed by the sheet's title (#110).

The bulletin gives no song titles for the 찬양 medley (the listed name is the band), so
each lead sheet's big top title is the only song identity. gasazip.com is a plain-HTML
Korean CCM lyrics site whose search covers the church's repertoire; titles are ambiguous
there (dozens of songs share a name), so candidates are ranked against the Vision-OCR
fragments we already have and only a confident match is used. Anything less — no match,
site change, offline — returns ``None`` and the caller falls back to local reassembly.

godpeople 403s scrapers and CCLI's API is paid/NDA'd; gasazip needs only a browser UA.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

import httpx

_BASE = "http://gasazip.com"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
_TIMEOUT = 10.0

# Fraction of a candidate's lyric bigrams that must appear in the OCR fragments. The
# right song scores near 1.0 (OCR reads every staff line, syllable splits don't matter
# after Hangul-only normalization); same-titled different songs score near 0.
_MATCH_THRESHOLD = 0.5
_TOP_N = 5  # search candidates to fetch and score


@dataclass
class Candidate:
    song_id: str
    title: str
    artist: str
    # Canonical lyric lines; a blank line marks a stanza break (chunk() convention).
    lines: list[str] = field(default_factory=list)


# Search rows only: href precedes class on search results (related-song rows on song
# pages have the attributes reversed, so this pattern skips them).
_RESULT = re.compile(
    r'<a href="/(\d+)" class="[^"]*gz-candy-song-row[^"]*">'
    r".*?<strong>(.*?)</strong>\s*<em>(.*?)</em>",
    re.S,
)
_LYRICS_DIV = re.compile(r'id="gasa-desktop"[^>]*>(.*?)</div>', re.S)
_TAG = re.compile(r"<[^>]+>")
_HANGUL_ONLY = re.compile(r"[^가-힣]")


def _clean(fragment: str) -> str:
    return html.unescape(_TAG.sub("", fragment)).strip()


def search(title: str) -> list[Candidate]:
    """Search gasazip by song title, returning candidates in site order (no lyrics yet).

    Raises:
        httpx.HTTPError: network failure or non-2xx response.
    """
    resp = httpx.get(
        f"{_BASE}/search.html", params={"q": title}, headers=_HEADERS, timeout=_TIMEOUT
    )
    resp.raise_for_status()
    return [
        Candidate(song_id=sid, title=_clean(t), artist=_clean(a))
        for sid, t, a in _RESULT.findall(resp.text)
    ]


def fetch_lyrics(song_id: str) -> list[str]:
    """Fetch one song page's lyric lines; blank lines mark stanza breaks.

    Raises:
        httpx.HTTPError: network failure or non-2xx response.
    """
    resp = httpx.get(f"{_BASE}/{song_id}", headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    m = _LYRICS_DIV.search(resp.text)
    if not m:
        return []
    # <br /> is followed by a literal newline in the markup — fold the pair into one
    # break so only an explicit <br /><br /> survives as a blank stanza-break line.
    text = re.sub(r"<br\s*/?>\s*", "\n", m.group(1))
    lines = [html.unescape(_TAG.sub("", ln)).strip() for ln in text.split("\n")]
    out: list[str] = []
    for ln in lines:
        if ln:
            out.append(ln)
        elif out and out[-1]:  # collapse runs of blanks, drop leading blanks
            out.append("")
    while out and not out[-1]:
        out.pop()
    return out


def _strip_header(cand: Candidate) -> None:
    """Drop a leading "제목 - 가수" header line some song pages embed in the lyrics."""
    if not cand.lines:
        return
    head = cand.lines[0].replace(" ", "")
    if cand.title.replace(" ", "") in head and cand.artist.replace(" ", "") in head:
        cand.lines = cand.lines[1:]
        while cand.lines and not cand.lines[0]:
            cand.lines.pop(0)


def _bigrams(text: str) -> set[str]:
    s = _HANGUL_ONLY.sub("", text)
    return {s[i : i + 2] for i in range(len(s) - 1)}


def _score(fragments: list[str], lines: list[str]) -> float:
    """Fraction of the candidate's lyric bigrams present in the OCR fragments."""
    lyric = _bigrams("".join(lines))
    if not lyric:
        return 0.0
    return len(lyric & _bigrams("".join(fragments))) / len(lyric)


def lookup(title: str, fragments: list[str]) -> Candidate | None:
    """Find the song matching the sheet: search by title, rank by OCR-fragment overlap.

    Returns the best candidate (with ``lines`` populated) when it clears the match
    threshold; ``None`` on no confident match or any network failure — the caller
    falls back to local transcription.
    """
    try:
        candidates = search(title)[:_TOP_N]
        best, best_score = None, 0.0
        for cand in candidates:
            cand.lines = fetch_lyrics(cand.song_id)
            _strip_header(cand)
            score = _score(fragments, cand.lines)
            if score > best_score:
                best, best_score = cand, score
    except httpx.HTTPError:
        return None
    if best is None or best_score < _MATCH_THRESHOLD:
        return None
    return best
