"""Transcribe Korean lyrics from band lead-sheet images — free, local, offline hybrid.

The band runs the arrangement live from the physical sheets, so the deck only needs the
*lyrics* present (not the red ×N / X-out / → arrangement marks). Two local stages, no API:

1. Apple Vision (``ocr_ko.swift``) reads the Korean text. High recall over busy musical
   notation and it never crashes on big images — but it returns each note's syllable as a
   separate fragment ("가 까 이"), so the lines need rebuilding.
2. A local Ollama model (default ``qwen2.5:14b``, in *text* mode) reassembles the fragments
   into clean lyric lines, in top-to-bottom page order. Running it as a text task sidesteps
   the vision-runner crash we hit feeding images directly, and keeps it offline and free.

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


def _vision_ocr(image_path: str) -> list[str]:
    """Run the Apple Vision OCR script, returning raw text lines top-to-bottom.

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
    return [ln for ln in result.stdout.splitlines() if ln.strip()]


# ── Stage 2: filter to lyric fragments ────────────────────────────────────────

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


# ── Stage 3: reassemble fragments into lines via a local model ────────────────

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
# cross-staff hymn verses (a ~27B-only skill that thrashes on a 24GB Mac); the operator
# regroups in review. Rule order matters on a 14B: recall is stated first so the model
# never drops the unnumbered second-staff lines or the chorus.
_PROMPT = """\
아래는 한국어 찬양 악보 한 장(곡 하나)에서 OCR로 추출한 가사 조각들입니다. 깨끗한 가사 줄 \
목록으로 정리하세요.

규칙(모두 지키세요):
1. 모든 가사를 하나도 빠짐없이 포함하세요. 번호 없는 줄과 후렴 줄도 전부. 어떤 가사도 \
생략·요약하지 마세요.
2. 음표마다 끊긴 음절을 자연스러운 단어로 붙이세요. 예: "죄에 서자 유-를 얻게-함은" → \
"죄에서 자유를 얻게 함은". 음절 끝의 "-"는 제거하고 띄어쓰기를 자연스럽게 고치세요.
3. 악보 한 단(staff system)의 가사 한 줄을 line 하나로 만드세요(줄바꿈 없이). 줄 순서는 \
위에서 아래로 그대로 유지하세요.
4. 줄 맨 앞의 절 번호("1." "2." "3." "4.")가 있으면 그대로 살려 두세요.
5. 악보에 곡이 하나면 song 도 하나만 만들고 모든 줄을 그 song.lines 에 순서대로 넣으세요. \
악보에 여러 곡이 있을 때만 곡별로 나누고 각 곡 제목을 title 로 쓰세요.
6. title = 악보 맨 위 큰 글씨 제목 한 줄. "Hymn 268" 같은 번호·출처 줄, "L.E.Jones"· \
"Scored by"·영어·연도, 반복되는 가사는 title 이 아닙니다.
7. 가사가 아닌 것은 제거: 코드, 마디 번호, 영어, 저작권/워터마크, 편곡 기호(V, C, B, 간주, \
키업, ×2, →), 섹션 라벨(Verse/Chorus/Bridge/Intro/Outro).

가사 조각들:
"""


def _reassemble(fragments: list[str]) -> list[Song]:
    """Ask the local Ollama model to rebuild fragments into clean lyric lines."""
    import httpx

    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    model = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")
    try:
        response = httpx.post(
            f"{host}/api/generate",
            json={
                "model": model,
                "prompt": _PROMPT + "\n".join(fragments),
                "stream": False,
                "think": False,  # disable thinking; qwen3.5 etc. otherwise return empty
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
    """Read one band-sheet image into its songs' lyric lines (free local hybrid).

    Apple Vision OCR -> Hangul-fragment filter -> local model line reassembly.
    Returns one Song (title + ordered lyric lines) per song on the sheet.

    Raises:
        RuntimeError: if `swift`/OCR fails or Ollama is unreachable.
    """
    fragments = _filter_lyric_fragments(_vision_ocr(image_path))
    return _reassemble(fragments)


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
