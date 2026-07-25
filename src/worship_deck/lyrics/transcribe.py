"""Transcribe Korean lyrics from band lead-sheet images — gasazip lookup, else review.

The band runs the arrangement live from the physical sheets, so the deck only needs the
*lyrics* present (not the red ×N / X-out / → arrangement marks). Pipeline per sheet:

1. Apple Vision (``ocr_ko.swift``) reads the Korean text with per-line heights. High
   recall over busy musical notation and it never crashes on big images — but it returns
   each note's syllable as a separate fragment ("가 까 이"), so the text is only usable as
   *search fragments*, never as slide lines.
2. Sheet-title candidates — the tallest Hangul lines near the top of the page, tallest
   first — are detected deterministically from the OCR heights (the bulletin names the
   band, not the songs, so the sheet title is the only song identity; #110, #202).
3. Canonical lyrics are looked up on gasazip.com by each title candidate (expanded into
   query variants, ``online.query_variants``) and ranked against the OCR fragments. The
   first confident match wins: clean text, no note-split syllables, no key-change repeats.
4. On a miss the song comes back **empty**, carrying the candidates the lookup already
   scored, and the operator picks the right one in review (#213). There is no local-model
   reassembly: its output was discarded every week and cost ~25s per sheet.

``transcribe()`` returns one ``Song`` per song on the sheet, or ``[]`` when the sheet has
no title at all (a continuation page — the caller folds its fragments into the previous
song). Chunking into <= 2-line slides (#18), song-to-slot matching (#19), and operator
review (#25) happen downstream.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from worship_deck.lyrics import linebreak, online, sections

# ── Data model ────────────────────────────────────────────────────────────────


@dataclass
class Song:
    title: str
    # Ordered, de-fragmented lyric lines (page order). A blank line marks a stanza break:
    # chunk() starts a fresh slide there — the same convention choir.py uses and how the
    # operator splits regrouped verses in review.
    lines: list[str] = field(default_factory=list)
    composer: str = ""  # composer/arranger credit line, shown on the title slide (choir)
    # Operator-labeled sections (#113): ordered {"label": str, "lines": list[str]} groups
    # (V1/C/B/PC…). Empty = unlabeled; the builder falls back to chunk(`lines`). When present,
    # `lines` is kept as the flattened mirror (sections joined by a blank line). See arranged_chunks().
    sections: list[dict] = field(default_factory=list)
    # The play-order string sequencing the section labels, e.g. "V1 C V1 Cx2 B Cx3". Empty =
    # play each section once in document order. See parse_arrangement()/arranged_chunks().
    arrangement: str = ""
    # The raw arrangement string read off the lead sheet (e.g. "V-C-V-Cx2-B-Cx3"), shown in
    # review as a non-binding hint for typing `arrangement`. Display-only — never parsed (#113).
    arrangement_hint: str = ""
    # Lyric origin for the review provenance badge (#200). Empty for typed/library songs
    # (no badge shown). gasazip match: {"source":"gasazip","song_id","artist","cand_cov",
    # "ocr_cov"} — the two coverages are the confidence readout. Lookup miss:
    # {"source":"ocr","titles":[…]} — no lyrics yet, review must pick (#213). May also carry
    # {"merged_sheets": n} when a continuation page was folded in. Origin, not current text.
    provenance: dict = field(default_factory=dict)
    # The filtered Hangul OCR fragments that scored this song's lookup, persisted so review
    # re-search (#203) can re-score gasazip candidates without re-running OCR (the sheet image
    # may be gone by then). Empty for typed/library songs.
    fragments: list[str] = field(default_factory=list)
    # gasazip candidates already fetched and scored by a lookup that found no confident match,
    # best first (``online.candidate_dict`` shape). Review renders the picker straight from
    # these, so a miss costs the operator one tap instead of a fresh throttled search (#213).
    candidates: list[dict] = field(default_factory=list)


# ── Stage 1: Apple Vision OCR ─────────────────────────────────────────────────

_OCR_SCRIPT = Path(__file__).with_name("ocr_ko.swift")


def _vision_ocr(image_path: str) -> list[tuple[float, str]]:
    """Run the Apple Vision OCR script, returning (height, text) lines top-to-bottom.

    Height is the line's tallest bounding box as a fraction of image height — the
    title-detection signal (the page title is the tallest Hangul line near the top).

    Raises:
        RuntimeError: if `swift` (Xcode Command Line Tools) is missing or OCR fails.
    """
    try:
        result = subprocess.run(
            ["swift", str(_OCR_SCRIPT), image_path],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError as e:  # `swift` not installed
        raise RuntimeError(
            "`swift` not found — Apple Vision OCR needs Xcode Command Line Tools "
            "(`xcode-select --install`)."
        ) from e
    if result.returncode != 0:
        raise RuntimeError(f"Vision OCR failed for {image_path}: {result.stderr.strip()}")
    lines = []
    for ln in result.stdout.splitlines():
        height, _, text = ln.partition("\t")
        if text.strip():
            lines.append((float(height), text.strip()))
    return lines


# ── Stage 2: detect the sheet title ──────────────────────────────────────────

_TITLE_REGION = 10  # OCR lines from the top of the page to consider
_TITLE_MIN_HANGUL_RATIO = 0.5  # of non-space chars; handwriting mixes latin/digits in
_TITLE_MAX_HANGUL = 16  # longer Hangul runs are note-split lyric lines, not titles
_TITLE_CANDIDATES = 3  # tall lines to try as lookup queries, tallest first (#202)
# Sheets print the credit on the title's own baseline ("하나님 아버지의 마음 Words & Music by
# 설경육"), and the English drags the Hangul ratio under the bar — 2026-07-26 sheet 2 lost its
# whole song this way. Everything from the credit marker on is cut before the line is judged.
_CREDIT = re.compile(r"(?i)\b(?:words?\s*&?\s*music|words?\s*by|music\s*by|scored\s*by|arr\.)|작사|작곡|편곡")


def _detect_titles(ocr_lines: list[tuple[float, str]]) -> list[str]:
    """Pick sheet-title candidates: the tallest mostly-Hangul lines near the top.

    Handwritten arrangement marks can be taller but are dominated by latin/digit/symbol
    glyphs (e.g. ``드럼만 - ((83)``), so a line only qualifies when at least half its
    non-space characters are Hangul; full lyric lines (continuation pages without their
    own title) are excluded by the Hangul length cap. Stray non-Hangul tokens merged
    into the title's baseline (e.g. a red "•all" mark) are trimmed off the edges.
    Returns up to ``_TITLE_CANDIDATES`` titles tallest-first — big garbled handwriting
    can out-height the printed title, so the lookup tries each in turn (#202) — or
    ``[]`` when nothing qualifies, and the caller then skips the online lookup.
    """
    candidates = []
    for height, raw in ocr_lines[:_TITLE_REGION]:
        if any(n in raw for n in _NOISE):
            continue
        text = _CREDIT.split(raw)[0].strip()
        hangul = len(_HANGUL.findall(text))
        nonspace = len(re.sub(r"\s", "", text))
        if not hangul or hangul > _TITLE_MAX_HANGUL:
            continue
        if not nonspace or hangul / nonspace < _TITLE_MIN_HANGUL_RATIO:
            continue
        candidates.append((height, text))
    titles: list[str] = []
    for _, text in sorted(candidates, key=lambda c: c[0], reverse=True)[:_TITLE_CANDIDATES]:
        tokens = text.split()
        while tokens and not _HANGUL.search(tokens[0]):
            tokens.pop(0)
        while tokens and not _HANGUL.search(tokens[-1]):
            tokens.pop()
        title = " ".join(tokens)
        if title and title not in titles:
            titles.append(title)
    return titles


# A single arrangement token: a section label (V/C/B or PC), an optional verse number, and an
# optional ×N repeat — e.g. "V", "C", "B", "PC", "V1", "Cx2", "PC×2", "Cx3".
_ARR_TOKEN = re.compile(r"(?i)^(?:PC|[VCB])\d*(?:[x×]\d+)?$")


def detect_arrangement_hint(ocr_lines: list[tuple[float, str]]) -> str:
    """Find the printed arrangement string near the top of the sheet (e.g. "V-C-V-Cx2-B-Cx3").

    Display-only (#113): returned verbatim as a hint the operator copies into a song's `order`,
    never parsed. A line qualifies only when every "-"/space-separated token is an arrangement
    token and there are at least three — which naturally excludes chord lines ("A C#m7 D",
    "Am C G") and lyric/credit text. Returns "" when no such line is found (e.g. handwritten
    marks Vision can't read).
    """
    for _, text in ocr_lines[:_TITLE_REGION]:
        tokens = [t for t in re.split(r"[-\s]+", text.strip()) if t]
        if len(tokens) >= 3 and all(_ARR_TOKEN.match(t) for t in tokens):
            return text.strip()
    return ""


# ── Stage 3: filter to lyric fragments ────────────────────────────────────────

_HANGUL = re.compile(r"[가-힣]")
# Hangul-bearing lines that are NOT lyrics (credits/instructions/phonetic titles/watermark).
_NOISE = ("도돌이표", "아이자야", "달하영")


def _filter_lyric_fragments(lines: list[str]) -> list[str]:
    """Keep only Korean lyric fragments — drops chords, measure numbers, English, URLs."""
    out = []
    for ln in lines:
        s = ln.strip()
        if not _HANGUL.search(s):  # chord symbols, numbers, English, watermark URL
            continue
        if any(n in s for n in _NOISE):
            continue
        out.append(s)
    return out


# ── Orchestration ─────────────────────────────────────────────────────────────


# A continuation page's lyrics are, by definition, already inside the previous song's
# canonical text. Measured on the 2026-07-26 sheets: the real continuation scores 0.93
# against its own song and 0.09 against the other, and a genuinely separate song whose
# title Vision missed scores 0.09 — so the gap is wide and 0.5 sits in the middle of it.
# "No title detected" is NOT the test: that sheet was a separate song (하나님 아버지의 마음)
# whose title carried an English credit, while the real continuation had a (misread) title.
_CONTINUATION_COV = 0.5


def _is_continuation(fragments: list[str], previous_lines: list[str]) -> bool:
    _, ocr_cov = online._covs(online._bigrams("".join(fragments)), previous_lines)
    return ocr_cov >= _CONTINUATION_COV


def transcribe(
    image_path: str,
    steps: dict[str, float] | None = None,
    previous_lines: list[str] | None = None,
) -> list[Song]:
    """Read one band-sheet image into its song's lyric lines.

    Apple Vision OCR (with line heights) -> deterministic title detection -> canonical
    lyrics lookup on gasazip ranked by the OCR fragments -> on a confident match the
    canonical text wins (a sheet page holds one song, possibly printed twice for a key
    change), re-broken to fit the lyric banner (``linebreak.rebreak``, #126).

    On a lookup miss the returned song has **no lyrics** — only the detected title, the
    OCR fragments, and the candidates the lookup already scored, so review shows the
    picker immediately (#213).

    ``previous_lines`` are the previous sheet's canonical lyrics, if it matched. When this
    sheet's fragments are already contained in them it is a continuation page, and the song
    comes back flagged ``provenance["continuation"]`` with nothing but its fragments — no
    lookup is attempted, and the caller folds it into that song.

    If `steps` is provided, per-stage durations (seconds) are written into it with keys
    "ocr" and "gasazip" (when a lookup ran).

    Raises:
        RuntimeError: if `swift`/OCR fails.
    """
    t = time.monotonic()
    ocr_lines = _vision_ocr(image_path)
    if steps is not None:
        steps["ocr"] = round(time.monotonic() - t, 1)

    titles = _detect_titles(ocr_lines)
    fragments = _filter_lyric_fragments([text for _, text in ocr_lines])
    if previous_lines and _is_continuation(fragments, previous_lines):
        return [
            Song(
                title="",
                fragments=fragments,
                provenance={"source": "ocr", "continuation": True},
            )
        ]

    # Each title candidate expands into search variants (note-split titles need their
    # syllables rejoined before gasazip finds anything); one budgeted lookup covers them all.
    queries = list(dict.fromkeys(q for title in titles for q in online.query_variants(title)))
    match, scored = None, []
    if queries:
        t = time.monotonic()
        match, scored = online.lookup(queries, fragments)
        if steps is not None:
            steps["gasazip"] = round(time.monotonic() - t, 1)

    # No title and not a continuation: a separate song Vision couldn't name. It still gets a
    # card — the operator types the title and re-searches, which beats losing the song.
    song = Song(title=titles[0] if titles else "",
                arrangement_hint=detect_arrangement_hint(ocr_lines))
    song.fragments = fragments  # kept for review re-search scoring (#203)
    if match:
        song.title, song.lines = match.title, linebreak.rebreak(match.lines)
        # Canonical text -> suggested section cards + page-order arrangement (#206);
        # the operator relabels/reorders in review. `lines` stays the flattened mirror.
        suggestion = sections.suggest(song.lines)
        if suggestion:
            song.sections, song.arrangement = suggestion
            song.lines = sections.flatten(song.sections)
        song.provenance = {
            "source": "gasazip",
            "song_id": match.song_id,
            "artist": match.artist,
            "cand_cov": match.cand_cov,
            "ocr_cov": match.ocr_cov,
        }
    else:
        # No lyrics: OCR text is note-split and unusable on a slide. The operator picks a
        # candidate (or corrects the title and re-searches) in review; the build endpoint
        # refuses a song still empty at that point.
        song.provenance = {"source": "ocr", "titles": titles}
        song.candidates = [online.candidate_dict(c) for c in scored]
    return [song]


def chunk(lines: list[str], max_lines: int = 2) -> list[list[str]]:
    """Group lyric lines into slides of at most ``max_lines`` lines.

    A blank/whitespace-only line forces a slide break (stanza boundary) and is not
    emitted as content. Returns a list of slides, each a list of 1..max_lines
    non-empty lines; an empty or all-blank input returns ``[]``.
    """
    slides: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if not line.strip():  # stanza break
            if current:
                slides.append(current)
                current = []
            continue
        current.append(line)
        if len(current) == max_lines:
            slides.append(current)
            current = []
    if current:
        slides.append(current)
    return slides


def parse_arrangement(s: str) -> list[str]:
    """Parse a play-order string into a list of section labels (#113).

    Splits on dashes/whitespace and drops empties: "V1 C V1 C B C" -> ["V1","C","V1","C","B","C"].
    There are no repeat counts — a section is replayed by repeating its label (the operator keeps
    the slide on screen for live ×N repeats, watching the band sheet), keeping the deck small.
    """
    return [t for t in re.split(r"[-\s]+", s.strip()) if t]


def arranged_chunks(song: Song) -> list[tuple[str, list[str]]]:
    """Chunk a song's lyrics into <=2-line slides, honoring its labeled sections + arrangement (#113).

    Returns (label, chunk) pairs in play order — the label rides along so the builder can stamp it
    into each slide's presenter notes (operator-only; hidden from the audience). When the song has
    no `sections` (choir/confession/legacy worship) this is chunk(song.lines) with empty labels.
    Otherwise each section's lines are chunked and played in the order given by `song.arrangement`
    (a play-order string of section labels); an empty arrangement plays each section once in
    document order. Labels in the arrangement that match no section are skipped (the UI warns).
    """
    if not song.sections:
        return [("", c) for c in chunk(song.lines)]
    by_label: dict[str, list[str]] = {}
    for sec in song.sections:
        lab = sec["label"].strip().upper()
        if lab:
            by_label.setdefault(lab, sec["lines"])
    labels = (
        parse_arrangement(song.arrangement)
        if song.arrangement.strip()
        else [sec["label"] for sec in song.sections]
    )
    out: list[tuple[str, list[str]]] = []
    for label in labels:
        lines = by_label.get(label.strip().upper())
        if lines is None:  # unknown label -> skip (UI warns)
            continue
        out.extend((label, c) for c in chunk(lines))
    return out
