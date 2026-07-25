"""Canonical worship-song lyrics from gasazip.com, keyed by the sheet's title (#110).

The bulletin gives no song titles for the 찬양 medley (the listed name is the band), so
each lead sheet's big top title is the only song identity. gasazip.com is a plain-HTML
Korean CCM lyrics site whose search covers the church's repertoire; titles are ambiguous
there (dozens of songs share a name), so candidates are ranked against the Vision-OCR
fragments we already have and only a confident match is used. Anything less — no match,
site change, offline — returns ``None`` along with everything it scored, and the operator
picks from those candidates in review (#213).

godpeople 403s scrapers and CCLI's API is paid/NDA'd; gasazip needs only a browser UA.
"""

from __future__ import annotations

import html
import logging
import re
import time
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

_BASE = "http://gasazip.com"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
_TIMEOUT = 10.0

# Acceptance (#202): a candidate passes when the OCR fragments cover at least
# _MATCH_THRESHOLD of its lyric bigrams — the right song scores near 1.0 (OCR reads
# every staff line, syllable splits don't matter after Hangul-only normalization) and
# same-titled different songs score near 0 — or, for canonical texts longer than the
# sheet (hymn pages print every verse, the sheet often has one), when its title
# resembles the query AND its lyrics cover at least _OCR_COV_MIN of the OCR's bigrams.
_MATCH_THRESHOLD = 0.5
_OCR_COV_MIN = 0.5
_FALLBACK_N = 5  # site-ranked rows to fetch when no title-similar row is accepted
_THROTTLE_S = 2.5  # spacing between requests — gasazip 429s after ~10 rapid ones
_FETCH_BUDGET = 8  # lyric pages fetched per sheet across all query variants (#213)
# Consecutive near-zero rows that mean a query landed in unrelated territory and its
# remaining rows aren't worth 2.5s each. The #202 fallback-row win (허무한 시절 지날 때 →
# 성령이 오셨네) was accepted on row 2, so a run of 3 never cuts a real match short.
_DEAD_END = 3
_DEAD_END_COV = 0.1


@dataclass
class Candidate:
    song_id: str
    title: str
    artist: str
    # Canonical lyric lines; a blank line marks a stanza break (chunk() convention).
    lines: list[str] = field(default_factory=list)
    # Both coverage directions from scoring, logged for threshold tuning (#202) and
    # surfaced by the review provenance badge (#200).
    cand_cov: float = 0.0
    ocr_cov: float = 0.0


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
# Trailing repeat marks some song pages embed in the lyric text ("…함없네(x2)") — repeats
# are the band's arrangement concern, not slide text (operator preference, 2026-07-16).
_REPEAT_MARK = re.compile(r"[(（]?\s*[xX×]\s*\d+\s*[)）]?\s*$")


def _clean(fragment: str) -> str:
    return html.unescape(_TAG.sub("", fragment)).strip()


_last_request = 0.0
_lyrics_cache: dict[str, list[str]] = {}


def _throttled_get(url: str, **kwargs) -> httpx.Response:
    """httpx.get with requests spaced >= _THROTTLE_S apart (no wait before the first)."""
    global _last_request
    wait = _last_request + _THROTTLE_S - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    try:
        return httpx.get(url, **kwargs)
    finally:
        _last_request = time.monotonic()


def search(title: str) -> list[Candidate]:
    """Search gasazip by song title, returning candidates in site order (no lyrics yet).

    Raises:
        httpx.HTTPError: network failure or non-2xx response.
    """
    resp = _throttled_get(
        f"{_BASE}/search.html", params={"q": title}, headers=_HEADERS, timeout=_TIMEOUT
    )
    resp.raise_for_status()
    return [
        Candidate(song_id=sid, title=_clean(t), artist=_clean(a))
        for sid, t, a in _RESULT.findall(resp.text)
    ]


def fetch_lyrics(song_id: str) -> list[str]:
    """Fetch one song page's lyric lines; blank lines mark stanza breaks.

    Trailing "(x2)"-style repeat marks are stripped. Cached per song_id for the
    process lifetime (lyrics are static); hits return a copy because callers
    (``_strip_header``) mutate the list.

    Raises:
        httpx.HTTPError: network failure or non-2xx response.
    """
    if song_id in _lyrics_cache:
        return list(_lyrics_cache[song_id])
    resp = _throttled_get(f"{_BASE}/{song_id}", headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    m = _LYRICS_DIV.search(resp.text)
    if not m:
        _lyrics_cache[song_id] = []
        return []
    # <br /> is followed by a literal newline in the markup — fold the pair into one
    # break so only an explicit <br /><br /> survives as a blank stanza-break line.
    text = re.sub(r"<br\s*/?>\s*", "\n", m.group(1))
    lines = [html.unescape(_TAG.sub("", ln)).strip() for ln in text.split("\n")]
    out: list[str] = []
    for ln in lines:
        stripped = _REPEAT_MARK.sub("", ln).strip()
        if ln and not stripped:
            continue  # the line was only a repeat mark — drop it, don't fake a stanza break
        if stripped:
            out.append(stripped)
        elif out and out[-1]:  # collapse runs of blanks, drop leading blanks
            out.append("")
    while out and not out[-1]:
        out.pop()
    _lyrics_cache[song_id] = out
    return list(out)


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


def _covs(ocr_bigrams: set[str], lines: list[str]) -> tuple[float, float]:
    """(cand_cov, ocr_cov): the bigram intersection over each side's bigram count."""
    lyric = _bigrams("".join(lines))
    inter = len(lyric & ocr_bigrams)
    return (
        inter / len(lyric) if lyric else 0.0,
        inter / len(ocr_bigrams) if ocr_bigrams else 0.0,
    )


def _title_similar(a: str, b: str) -> bool:
    """Hangul-normalized containment either way (site titles add parentheses/artist)."""
    na, nb = _HANGUL_ONLY.sub("", a), _HANGUL_ONLY.sub("", b)
    if len(na) > len(nb):
        na, nb = nb, na
    return len(na) >= 2 and na in nb


_MELISMA = re.compile(r"[-‐–—]")
_MIN_SEGMENT_QUERY = 4  # Hangul chars; shorter first segments ("말씀") match half the site


def _note_split(title: str) -> bool:
    """Is this "title" really a lyric line Vision read syllable-by-syllable off the staff?"""
    tokens = title.split()
    singles = sum(1 for t in tokens if len(t) == 1)
    return len(tokens) >= 4 and singles * 2 >= len(tokens)


def query_variants(title: str) -> list[str]:
    """Search queries to try for one detected sheet title, best guess first (#213).

    A title read off the staff comes back note-split — ``말 씀 앞 에서- 경 외 함 으로-`` — and
    gasazip matches literally, so the raw string finds nothing related (it tokenizes on
    spaces and matches stray syllables). The melisma hyphens mark where a sung word ends,
    so splitting on them and joining the syllables inside each segment reconstructs the
    words: ``말씀앞에서 경외함으로 주께홀로니다``, whose first segment alone is an exact title
    hit. Joining *everything* is wrong — the site stores spaced text and returns 0 rows.

    Normal titles (no note-splitting) yield just themselves, so nothing extra is fetched.
    """
    title = title.strip()
    if not title or not _note_split(title):
        return [title] if title else []
    segments = [s for s in ("".join(p.split()) for p in _MELISMA.split(title)) if s]
    variants = []
    if segments and len(_HANGUL_ONLY.sub("", segments[0])) >= _MIN_SEGMENT_QUERY:
        variants.append(segments[0])
    if len(segments) > 1:
        variants.append(" ".join(segments))
    variants.append(title)  # last: the raw string rarely wins, but costs one search
    return list(dict.fromkeys(variants))


def lookup(
    queries: list[str], fragments: list[str], budget: int = _FETCH_BUDGET
) -> tuple[Candidate | None, list[Candidate]]:
    """Find the song matching the sheet: search each query, rank by OCR-fragment overlap.

    All search rows are considered — the right song often sits past the first few
    (#202): rows whose title resembles the query are fetched and scored first; if none
    is accepted, the first ``_FALLBACK_N`` remaining rows in site order are tried —
    gasazip's search indexes lyrics, so a first-line "title" still surfaces the right
    song under a dissimilar name. ``queries`` are tried in order (see `query_variants`)
    until a candidate passes the acceptance gate, with at most ``budget`` lyric pages
    fetched across all of them — each fetch waits ``_THROTTLE_S``, so an unbounded scan
    is the difference between a 5s and a 40s sheet.

    Returns ``(match, scored)``: the accepted candidate or ``None``, plus everything
    scored along the way (best first, ``lines`` populated). On a miss the caller stashes
    ``scored`` on the song so review can offer the picker with no further fetching (#213).
    """
    ocr = _bigrams("".join(fragments))
    scored: list[Candidate] = []
    seen: set[str] = set()

    def by_score() -> list[Candidate]:
        return sorted(scored, key=lambda c: c.cand_cov, reverse=True)

    try:
        for query in queries:
            rows = search(query)
            similar = [c for c in rows if _title_similar(query, c.title)]
            rest = [c for c in rows if not _title_similar(query, c.title)]
            cold = 0
            for cand in similar + rest[:_FALLBACK_N]:
                if cand.song_id in seen:
                    continue
                if budget <= 0:
                    logger.info("gasazip: fetch budget exhausted for %r", query)
                    return None, by_score()
                seen.add(cand.song_id)
                cand.lines = fetch_lyrics(cand.song_id)
                budget -= 1
                _strip_header(cand)
                cand.cand_cov, cand.ocr_cov = _covs(ocr, cand.lines)
                scored.append(cand)
                logger.info(
                    "gasazip %s '%s' (%s): cand_cov=%.2f ocr_cov=%.2f",
                    cand.song_id, cand.title, cand.artist, cand.cand_cov, cand.ocr_cov,
                )
                if cand.cand_cov >= _MATCH_THRESHOLD or (
                    cand in similar and cand.ocr_cov >= _OCR_COV_MIN
                ):
                    logger.info("gasazip match for %r: %s '%s'", query, cand.song_id, cand.title)
                    return cand, by_score()
                cold = cold + 1 if max(cand.cand_cov, cand.ocr_cov) < _DEAD_END_COV else 0
                if cold >= _DEAD_END:
                    logger.info("gasazip: %r is a dead end, skipping its remaining rows", query)
                    break
            logger.info("gasazip: no confident match for %r (%d rows)", query, len(rows))
    except httpx.HTTPError:
        return None, by_score()
    return None, by_score()


def candidate_dict(cand: Candidate) -> dict:
    """JSON shape the review candidate picker consumes (assemble-time and /research)."""
    return {
        "song_id": cand.song_id,
        "title": cand.title,
        "artist": cand.artist,
        "cand_cov": cand.cand_cov,
        "ocr_cov": cand.ocr_cov,
        "preview": [ln for ln in cand.lines if ln.strip()][:4],
    }


def search_scored(title: str, fragments: list[str], limit: int = _FALLBACK_N) -> list[Candidate]:
    """Search gasazip and return the top rows scored against the OCR fragments, best first.

    The manual counterpart to ``lookup`` for review re-search (#203): the operator has
    corrected the title, so this applies **no** acceptance threshold and returns every
    scored candidate (``lines`` populated) for them to pick from. Rows whose title resembles
    the query are fetched first, then the rest in site order, capped at ``limit`` pages to
    bound latency and gasazip's rate limit (each fetch is throttled ``_THROTTLE_S`` apart).
    Sorted by ``cand_cov`` descending. Raises ``httpx.HTTPError`` on any network failure.
    """
    ocr = _bigrams("".join(fragments))
    rows = search(title)
    similar = [c for c in rows if _title_similar(title, c.title)]
    rest = [c for c in rows if not _title_similar(title, c.title)]
    cands = (similar + rest)[:limit]
    for cand in cands:
        cand.lines = fetch_lyrics(cand.song_id)
        _strip_header(cand)
        cand.cand_cov, cand.ocr_cov = _covs(ocr, cand.lines)
    cands.sort(key=lambda c: c.cand_cov, reverse=True)
    return cands
