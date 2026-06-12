"""Phrase-aware re-breaking of transcribed lyric lines (#126).

The worship/고백 lyric banners are fixed-width autoshrink boxes and ``chunk()`` groups
lines 2-per-slide with no notion of fit, so over-long transcribed lines render small and
cramped. ``rebreak()`` runs inside ``transcribe()`` — after gasazip lookup or Ollama
reassembly, before results are persisted for review — collapsing adjacent repeated
phrases to ``… X N`` and splitting still-over-long lines at musical-phrase boundaries
(local Ollama; rule-based split at the best space when Ollama is unreachable or its
output fails validation, so Ollama is never a hard dependency of the gasazip path).

Fit model (same glyph-advance model as keynote/build.py, #115): measured on master.key,
the worship (slide 8) and 고백 (slide 60) lyric banners are identical — on-canvas text
item 1763pt wide, base font 87pt — so one constant serves both. Full width holds
1763/(87*0.83) ≈ 24 Hangul chars, but full-width lines read congested (the 2026-06-07
deck's slide-8 defect line is exactly 24 chars; the template's own comfortable lines run
≤21), so the cap applies a 0.92 fill.
"""

from __future__ import annotations

import json
import os

import httpx

_LYRIC_BOX_W = 1763  # pt — lyric banner text-item width (master.key slides 8 and 60)
_LYRIC_FONT = 87  # pt — its base font
_CHAR_W_KO = 0.83  # avg Hangul glyph advance / font — matches keynote/build.py (#115)
_FILL = 0.92  # headroom below the geometric maximum; see module docstring
MAX_CHARS = int(_LYRIC_BOX_W * _FILL / (_LYRIC_FONT * _CHAR_W_KO))  # 22

# Don't collapse repeats of a unit this short: melisma syllables ("아 아 아") read
# better sung out than as "아 X 3".
_MIN_COLLAPSE_CHARS = 2


def collapse_repeats(line: str) -> str:
    """Collapse adjacent repeated phrases in one line to ``phrase X N``.

    Token (space-separated) level, longest group first, so
    ``물이 바다덮음같이 물이 바다덮음같이`` becomes ``물이 바다덮음같이 X 2`` rather than
    two single-token collapses. Non-adjacent repeats are left alone.
    """
    tokens = line.split()
    changed = True
    while changed:
        changed = False
        for g in range(len(tokens) // 2, 0, -1):
            for i in range(len(tokens) - 2 * g + 1):
                group = tokens[i : i + g]
                if len("".join(group)) < _MIN_COLLAPSE_CHARS:
                    continue
                n = 1
                while tokens[i + n * g : i + (n + 1) * g] == group:
                    n += 1
                if n >= 2:
                    tokens[i : i + n * g] = group + ["X", str(n)]
                    changed = True
                    break
            if changed:
                break
    return " ".join(tokens)


def _split_at_space(line: str, max_chars: int) -> list[str]:
    """Rule-based fallback: greedy split at spaces so each part fits ``max_chars``.

    Splits between units — words, except an ``X N`` repeat suffix is fused to the word
    before it so it can never be orphaned. A single overlong unit stays whole and
    autoshrinks slightly.
    """
    tokens = line.split()
    rest: list[str] = []
    i = 0
    while i < len(tokens):
        if rest and tokens[i] == "X" and i + 1 < len(tokens) and tokens[i + 1].isdigit():
            rest[-1] += f" X {tokens[i + 1]}"
            i += 2
        else:
            rest.append(tokens[i])
            i += 1
    parts: list[str] = []
    while rest:
        cur = [rest.pop(0)]
        while rest and len(" ".join([*cur, rest[0]])) <= max_chars:
            cur.append(rest.pop(0))
        parts.append(" ".join(cur))
    return parts


_SPLIT_FORMAT = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {"type": "array", "items": {"type": "string"}},
        }
    },
    "required": ["lines"],
}

# Rule 1 (must split into >= 2 pieces) is load-bearing: every line sent here is
# over-long by construction, but on barely-over lines the model otherwise returns the
# line unsplit. Worked examples in rules 4-5 are likewise needed — without the X-N
# example the model orphans the repeat suffix.
_SPLIT_PROMPT = """\
아래 한국어 찬양 가사 줄들은 슬라이드 한 줄에 넣기에 너무 깁니다. 각 줄을 노래할 때 \
호흡이 끊기는 악구(musical phrase)/의미 단위 경계에서 더 짧은 줄들로 나누세요.

규칙(모두 지키세요):
1. 모든 줄이 너무 깁니다 — 각 줄을 반드시 2개 이상의 조각으로 나누세요. 줄을 그대로 \
두면 안 됩니다.
2. 글자를 더하거나 빼거나 바꾸지 마세요. 조각들을 공백으로 이어 붙이면 원래 줄과 정확히 \
같아야 합니다. 띄어쓰기 위치에서만 나누세요.
3. 각 조각은 공백 포함 {max_chars}자 이하로 하세요. 나눈 뒤에도 {max_chars}자를 넘는 \
조각이 있으면 그 조각을 한 번 더 나누세요.
4. 단어나 조사 중간이 아니라 악구가 자연스럽게 끝나는 곳에서 나누세요. 예: \
"이전에 있는 것은 모두 잊어버리고 앞에 계신 그리스도께로 달려가 노라" → \
["이전에 있는 것은 모두 잊어버리고", "앞에 계신 그리스도께로 달려가 노라"]
5. "X 2" 같은 반복 표시는 바로 앞 구절과 같은 조각에 붙여 두세요. 예: \
"온세상 가득하리라 물이 바다덮음같이 X 2" → ["온세상 가득하리라", "물이 바다덮음같이 X 2"]
6. 입력 줄 순서 그대로, 입력 줄마다 조각 배열 하나씩 lines 에 넣으세요.

나눌 입력 가사 줄들은 다음과 같습니다:
"""


def _split_with_ollama(lines: list[str], max_chars: int) -> list[list[str]]:
    """Ask the local Ollama model to split each line at a phrase boundary.

    Returns one list of parts per input line. Raises ``httpx.HTTPError`` or
    ``ValueError`` on an unreachable server or unparseable response — callers fall
    back to :func:`_split_at_space`.

    Same ``OLLAMA_MODEL`` as reassembly: the 2026-06-11 bake-off picked qwen3:14b
    for both tasks once the reassembly prompt stopped it renumbering lines.
    """
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    model = os.environ.get("OLLAMA_MODEL", "qwen3:14b")
    response = httpx.post(
        f"{host}/api/generate",
        json={
            "model": model,
            "prompt": _SPLIT_PROMPT.format(max_chars=max_chars) + "\n".join(lines),
            "stream": False,
            "think": True,  # measurably better recall/spacing on qwen3:14b (bake-off)
            "format": _SPLIT_FORMAT,
            "options": {"temperature": 0},
        },
        timeout=120,  # tiny task; a hung Ollama must not stall assemble before the fallback
    )
    response.raise_for_status()
    body = response.json()
    data = json.loads(body.get("response") or body.get("thinking") or "")
    return data.get("lines") or []


def _valid_split(original: str, parts: object, max_chars: int) -> bool:
    """Accept a model split only if it preserves the characters and fits the box.

    Whitespace-insensitive comparison — the model may retidy fragmented OCR spacing
    (e.g. "주의보 혈 능력 있 도 다"), which is welcome. ``max_chars + 2`` tolerance:
    a couple of chars over only autoshrinks slightly.
    """
    if not isinstance(parts, list) or not parts:
        return False
    if not all(isinstance(p, str) and p.strip() for p in parts):
        return False
    if any(p.strip() == "X" or p.strip().isdigit() or p.strip().startswith("X ") for p in parts):
        return False  # orphaned "X N" repeat suffix
    if "".join(parts).replace(" ", "") != original.replace(" ", ""):
        return False
    return all(len(p.strip()) <= max_chars + 2 for p in parts)


def rebreak(lines: list[str], *, max_chars: int = MAX_CHARS) -> list[str]:
    """Collapse repeats and split over-long lyric lines at phrase boundaries.

    Blank lines (stanza breaks, the ``chunk()`` convention) pass through untouched and
    are never merged across. When no line exceeds ``max_chars`` after collapsing, no
    I/O happens at all; otherwise one batched Ollama call covers the over-long lines,
    and any failure degrades per line to the rule-based split. Never raises on Ollama
    problems.
    """
    # Collapse pass: repeats within a line, then identical adjacent lines.
    groups: list[tuple[str, int]] = []  # (collapsed line, adjacent repeat count)
    for raw in lines:
        if not raw.strip():
            groups.append(("", 1))
            continue
        text = collapse_repeats(raw.strip())
        if groups and groups[-1][0] == text:
            groups[-1] = (text, groups[-1][1] + 1)
        else:
            groups.append((text, 1))
    collapsed = [f"{text} X {n}" if n > 1 else text for text, n in groups]

    long_idx = [i for i, ln in enumerate(collapsed) if len(ln) > max_chars]
    if not long_idx:
        return collapsed

    try:
        model_splits = _split_with_ollama([collapsed[i] for i in long_idx], max_chars)
    except (httpx.HTTPError, ValueError):
        model_splits = []
    out: list[str] = []
    for i, ln in enumerate(collapsed):
        if i not in long_idx:
            out.append(ln)
            continue
        j = long_idx.index(i)
        parts = model_splits[j] if j < len(model_splits) else None
        if _valid_split(ln, parts, max_chars):
            out.extend(p.strip() for p in parts)
        else:
            out.extend(_split_at_space(ln, max_chars))
    return out
