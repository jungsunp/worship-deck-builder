"""Transcribe Korean lyrics from band lead-sheet images — free, local, offline hybrid.

The band runs the arrangement live from the physical sheets, so the deck only needs the
*lyrics* present (not the red ×N / X-out / → arrangement marks). Two local stages, no API:

1. Apple Vision (``ocr_ko.swift``) reads the Korean text. High recall over busy musical
   notation and it never crashes on big images — but it returns each note's syllable as a
   separate fragment ("가 까 이"), so the lines need rebuilding.
2. A local Ollama model (default ``qwen3.5:27b``, in *text* mode) reassembles the fragments
   into clean lyric lines. Running it as a text task sidesteps the vision-runner crash we
   hit feeding images directly, and keeps the whole thing offline and free.

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
    lines: list[str] = field(default_factory=list)  # ordered, de-fragmented lyric lines


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

_PROMPT = """\
아래는 한국어 찬양 악보에서 OCR로 추출한 가사 조각들입니다. 음표마다 끊겨 있어 한 단어의 \
음절이 여러 조각으로 분리돼 있습니다 (예: "가 까 이" → "가까이"). 끝에 붙은 "-"는 음을 끄는 \
표시이지 글자가 아닙니다.

규칙:
- 모든 가사를 빠짐없이 포함하세요. 요약하거나 줄을 생략하거나 합치지 마세요.
- 음표 단위로 분리된 음절을 자연스러운 단어/줄(악구)로 재조합하세요.
- 가사가 아닌 것은 모두 제거하세요: 섹션 라벨(Verse/Chorus/Bridge), 편곡 기호(V, V1, C, B, \
간주, 키업, ×2, →), 코드, 마디 번호, 영어, 저작권/워터마크.
- 악보에 여러 곡이 있으면 곡별로 나누고, 각 곡의 제목(악보 상단의 큰 글씨)을 title 로 쓰세요.

가사 조각들:
"""


def _reassemble(fragments: list[str]) -> list[Song]:
    """Ask the local Ollama model to rebuild fragments into clean lyric lines."""
    import httpx

    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    model = os.environ.get("OLLAMA_MODEL", "qwen3.5:27b")
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
    return [
        Song(title=song.get("title", "").strip(), lines=list(song.get("lines", [])))
        for song in data.get("songs", [])
    ]


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


def chunk(lines: list[str], max_lines: int = 2) -> list[str]:
    """Group lyric lines into <= max_lines per slide."""
    raise NotImplementedError
