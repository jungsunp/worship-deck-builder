"""Transcribe Korean lyrics from band lead-sheet images — online lookup, local fallback.

The band runs the arrangement live from the physical sheets, so the deck only needs the
*lyrics* present (not the red ×N / X-out / → arrangement marks). Pipeline per sheet:

1. Apple Vision (``ocr_ko.swift``) reads the Korean text with per-line heights. High
   recall over busy musical notation and it never crashes on big images — but it returns
   each note's syllable as a separate fragment ("가 까 이"), so the lines need rebuilding.
2. The sheet's title — the tallest Hangul line near the top of the page — is detected
   deterministically from the OCR heights (the bulletin names the band, not the songs,
   so the sheet title is the only song identity; #110).
3. Canonical lyrics are looked up on gasazip.com by that title, ranked against the OCR
   fragments (``online.lookup``). A confident match wins: clean text, no note-split
   syllables, no duplicated key-change repeats.
4. Otherwise a local Ollama model (default ``qwen2.5:14b``, in *text* mode) reassembles
   the fragments into clean lyric lines, in top-to-bottom page order — the original
   free/offline path. Running it as a text task sidesteps the vision-runner crash we hit
   feeding images directly.

The model returns lyrics *flat* (one line per staff line, page order). It is **not** asked
to regroup numbered hymn verses whose lyrics span two staff systems — that cross-staff
stitching is a capability only a ~27B model has, and 27B thrashes on a 24GB Mac. So for
such hymns the operator regroups the verses in the review app (#25): blank lines between
stanzas survive into ``Song.lines`` and ``chunk()`` then gives each stanza its own slide.

``transcribe()`` returns one ``Song`` per song on the sheet. Chunking into <= 2-line slides
(#18), song-to-slot matching (#19), and operator review (#25) happen downstream.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from worship_deck.lyrics import linebreak, online

# ── Data model ────────────────────────────────────────────────────────────────


@dataclass
class Song:
    title: str
    # Ordered, de-fragmented lyric lines (page order). A blank line marks a stanza break:
    # chunk() starts a fresh slide there — the same convention choir.py uses and how the
    # operator splits regrouped verses in review.
    lines: list[str] = field(default_factory=list)
    composer: str = ""  # composer/arranger credit line, shown on the title slide (choir)


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


def _detect_title(ocr_lines: list[tuple[float, str]]) -> str:
    """Pick the sheet title: the tallest mostly-Hangul line near the top of the page.

    Handwritten arrangement marks can be taller but are dominated by latin/digit/symbol
    glyphs (e.g. ``드럼만 - ((83)``), so a line only qualifies when at least half its
    non-space characters are Hangul; full lyric lines (continuation pages without their
    own title) are excluded by the Hangul length cap. Stray non-Hangul tokens merged
    into the title's baseline (e.g. a red "•all" mark) are trimmed off the edges.
    Returns "" when nothing qualifies — the caller then skips the online lookup.
    """
    candidates = []
    for height, text in ocr_lines[:_TITLE_REGION]:
        if any(n in text for n in _NOISE):
            continue
        hangul = len(_HANGUL.findall(text))
        nonspace = len(re.sub(r"\s", "", text))
        if not hangul or hangul > _TITLE_MAX_HANGUL:
            continue
        if hangul / nonspace < _TITLE_MIN_HANGUL_RATIO:
            continue
        candidates.append((height, text))
    if not candidates:
        return ""
    _, text = max(candidates, key=lambda c: c[0])
    tokens = text.split()
    while tokens and not _HANGUL.search(tokens[0]):
        tokens.pop(0)
    while tokens and not _HANGUL.search(tokens[-1]):
        tokens.pop()
    return " ".join(tokens)


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


# ── Stage 4 (fallback): reassemble fragments into lines via a local model ─────

_OLLAMA_FORMAT = {
    "type": "object",
    "properties": {
        "songs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "lines": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "lines"],
            },
        }
    },
    "required": ["songs"],
}

# Flat reassembly only — recall first. We deliberately do NOT ask the model to regroup
# cross-staff hymn verses (a ~27B-only skill); the operator regroups in review. Rule
# order matters on a 14B: recall is stated first so the model never drops the unnumbered
# second-staff lines or the chorus. The v3 prompt (2026-06-11 bake-off, see
# docs/gotchas.md): hyphen removal is a hard postcondition, three worked examples cover
# the real OCR defect patterns, the faithfulness rule blocks word substitution, and
# 절 번호 are stripped — verse numbers never belong on a lyric slide. Keep the "-" in
# the model INPUT: pre-stripping them in code degraded qwen3:14b (they are join cues).
_PROMPT = """\
아래는 한국어 찬양 악보 한 장에서 OCR로 추출한 가사 조각들입니다. 악보에서는 음표마다 \
음절이 끊어져 있고, 음을 길게 끄는 멜리스마 표시 "-" 가 섞여 있습니다. 이것을 자연스러운 \
한국어 가사 줄 목록으로 복원하세요.

규칙(모두 지키세요):
1. 모든 가사를 하나도 빠짐없이 포함하세요. 번호 없는 줄과 후렴 줄도 전부. 어떤 가사도 \
생략·요약하지 마세요.
2. 하는 일은 네 가지뿐입니다: 끊어진 음절 붙이기, "-" 제거, 띄어쓰기 교정, 줄 맨 앞 절 \
번호 제거. 가사 단어를 비슷한 다른 단어로 바꾸거나 글자를 더하지 마세요.
3. "-" 는 악보의 길게-끌기 표시일 뿐 가사가 아닙니다. 출력의 어떤 줄에도 "-" 가 한 개도 \
남으면 안 됩니다.
4. 끊어진 음절을 단어로 붙이고, 띄어쓰기를 표준 한국어 맞춤법대로 고치세요. 조사(을/를/이/\
가/은/는/에/의/께 등)는 반드시 앞 단어에 붙여 쓰세요. 예:
   "주 님 을 가 까 이 함 이 내 게 복 이 라" → "주님을 가까이 함이 내게 복이라"
   "나 의 생명을드- 리니 주영광위- 하여 - 사용하옵소서" → "나의 생명을 드리니 주 영광 위하여 사용하옵소서"
   "죄에 서자 유-를 얻게-함은" → "죄에서 자유를 얻게 함은"
5. 악보 한 단(staff system)의 가사 한 줄을 line 하나로 만드세요(줄바꿈 없이). 줄 순서는 \
위에서 아래로 그대로 유지하세요.
6. 절 번호는 가사가 아닙니다. 조각 맨 앞의 절 번호("1." "2." "3." "4.")는 제거하고 가사만 \
남기세요. 출력의 어떤 줄도 숫자 번호로 시작하면 안 됩니다.
7. 악보에 곡이 하나면 song 도 하나만 만들고 모든 줄을 그 song.lines 에 순서대로 넣으세요. \
악보에 여러 곡이 있을 때만 곡별로 나누고 각 곡 제목을 title 로 쓰세요.
8. title = 악보 맨 위 큰 글씨 제목 한 줄. "Hymn 268" 같은 번호·출처 줄, "L.E.Jones"· \
"Scored by"·영어·연도, 반복되는 가사는 title 이 아닙니다.
9. 가사가 아닌 것은 제거: 코드, 마디 번호, 영어, 저작권/워터마크, 편곡 기호(V, C, B, 간주, \
키업, ×2, →), 섹션 라벨(Verse/Chorus/Bridge/Intro/Outro).
"""


def _reassemble(fragments: list[str], title: str = "") -> list[Song]:
    """Ask the local Ollama model to rebuild fragments into clean lyric lines.

    When the sheet title was already detected from the OCR heights, it is given to the
    model so rule 6 (title guessing) no longer applies to it.
    """
    import httpx

    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    model = os.environ.get("OLLAMA_MODEL", "qwen3:14b")
    prompt = _PROMPT
    if title:
        prompt += f'이 악보의 곡 제목은 "{title}" 입니다. title 에 그대로 사용하세요.\n'
    prompt += "\n가사 조각들:\n"
    try:
        response = httpx.post(
            f"{host}/api/generate",
            json={
                "model": model,
                "prompt": prompt + "\n".join(fragments),
                "stream": False,
                "think": True,  # measurably better recall/spacing on qwen3:14b (bake-off)
                "format": _OLLAMA_FORMAT,
                "options": {"temperature": 0},
            },
            timeout=600,
        )
        response.raise_for_status()
    except httpx.HTTPError as e:
        raise RuntimeError(
            f"Ollama request to {host} (model {model}) failed: {e}. "
            "Is `ollama serve` running and the model pulled?"
        ) from e

    body = response.json()
    # Thinking models put the structured output in `thinking` when `response` is empty.
    data = json.loads(body.get("response") or body.get("thinking") or "")
    songs = []
    for song in data.get("songs", []):
        # Drop blank lyric lines and any empty song (the model occasionally emits an
        # empty trailing song).
        lines = [ln.strip() for ln in song.get("lines", []) if ln.strip()]
        if lines:
            songs.append(Song(title=song.get("title", "").strip(), lines=lines))
    return songs


# ── Orchestration ─────────────────────────────────────────────────────────────


def transcribe(image_path: str) -> list[Song]:
    """Read one band-sheet image into its songs' lyric lines.

    Apple Vision OCR (with line heights) -> deterministic title detection -> canonical
    lyrics lookup on gasazip ranked by the OCR fragments -> on a confident match, the
    canonical text wins (a sheet page holds one song, possibly printed twice for a key
    change). Otherwise falls back to local Ollama reassembly of the fragments, which
    also handles the rare multi-song page. Either way the lines are re-broken to fit
    the lyric banner (repeat collapse + phrase-boundary splits, ``linebreak.rebreak``,
    #126) before they reach review.

    Raises:
        RuntimeError: if `swift`/OCR fails, or the fallback is needed and Ollama is
            unreachable.
    """
    ocr_lines = _vision_ocr(image_path)
    title = _detect_title(ocr_lines)
    fragments = _filter_lyric_fragments([text for _, text in ocr_lines])
    if title:
        match = online.lookup(title, fragments)
        if match:
            return [Song(title=match.title, lines=linebreak.rebreak(match.lines))]
    songs = _reassemble(fragments, title=title)
    for song in songs:
        song.lines = linebreak.rebreak(song.lines)
    return songs


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
