"""Suggest section cards (V1/V2/C/B…) from canonical lyric structure (#206).

gasazip pages mostly print lyrics as one unbroken line stream — no stanza breaks —
so on a song's first encounter the operator hand-splits and hand-labels every
section card in the review UI (#113). But the structure is recoverable with no AI:

- **Stanza mode** — when the page does have stanza breaks (blank lines), they are
  authored section boundaries: each stanza is a block, and a stanza that *starts
  with* an already-seen block is that block plus a trailing remainder (chorus +
  closing tag). Blocks are never split from the end — suffix-splitting is what
  fragments a refrain line shared by verse and chorus (말씀하시면).
- **Tiling mode** — with no breaks, sections still *repeat verbatim* in the
  canonical text (V C V C C…): find the repeated line blocks and tile the stream
  with them. Matching is verbatim only (whitespace-insensitive): fuzzy bigram
  matching was tested and near-identical verses still don't chain. Any block
  under 2 lines means the repetition is a shared refrain line / per-verse hymn
  refrain / substitution verse, not section structure — every mislabeled sheet in
  the 8-week eval had one — so the suggestion is suppressed. Sole exception: a
  lone trailing echo of a section's last line (하나님 아버지의 마음), which is TAG.

Either way, distinct blocks are labeled by occurrence pattern and the suggested
``arrangement`` is the block sequence in page order, so an untouched review still
builds the exact original stream — the operator only overwrites it with the
week's real play order (red sheet marks). Songs with no repeated multi-line block
return None and review keeps today's single unlabeled card.
"""

from __future__ import annotations

import re

_MIN_REPEAT = 2  # a repeated span must be >= this many lines to mark a block (tiling mode)


def _norm(line: str) -> str:
    return re.sub(r"\s+", "", line)


def _split_stanzas(lines: list[str]) -> list[list[str]]:
    stanzas: list[list[str]] = []
    cur: list[str] = []
    for line in lines:
        if line.strip():
            cur.append(line)
        elif cur:
            stanzas.append(cur)
            cur = []
    if cur:
        stanzas.append(cur)
    return stanzas


def _stanza_blocks(stanzas: list[list[str]]) -> tuple[list[int], list[list[str]]]:
    """Blocks from authored stanza breaks: (occurrence sequence, distinct cards).

    A stanza beginning with an already-seen card (longest first) is peeled into
    that card + remainder, repeatedly — so "chorus + tag" and doubled stanzas
    resolve to known cards. A never-seen stanza (or remainder) becomes a new card
    whole; later stanzas never split it retroactively.
    """
    cards: list[list[str]] = []
    keys: list[tuple[str, ...]] = []
    seq: list[int] = []
    for stanza in stanzas:
        rest = stanza
        while rest:
            t = tuple(_norm(x) for x in rest)
            for i in sorted(range(len(cards)), key=lambda i: len(keys[i]), reverse=True):
                length = len(keys[i])
                if length <= len(t) and t[:length] == keys[i]:
                    seq.append(i)
                    rest = rest[length:]
                    break
            else:
                cards.append(rest)
                keys.append(t)
                seq.append(len(cards) - 1)
                rest = []
    return seq, cards


def _segment(toks: list[str]) -> list[tuple[int, int]]:
    """Tile an unbroken stream into (start, end) blocks aligned on verbatim repeats."""
    n = len(toks)
    # lcp[i][j] = length of the longest common prefix of suffixes i and j
    lcp = [[0] * (n + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(n - 1, -1, -1):
            if i != j and toks[i] == toks[j]:
                lcp[i][j] = lcp[i + 1][j + 1] + 1

    def longest_repeat_at(p: int) -> int:
        return max((lcp[p][j] for j in range(n) if j != p), default=0)

    # boundary wherever a repeated span of >= _MIN_REPEAT lines starts or ends
    starts = {0, n}
    for i in range(n):
        best = longest_repeat_at(i)
        if best >= _MIN_REPEAT:
            starts.add(i)
            starts.add(i + best)
    bounds = sorted(starts)

    # greedy left-to-right tiling: reuse an already-discovered block when it
    # matches here, else take the longest repeated prefix, else extend the
    # unique region to the next boundary
    blocks: list[tuple[int, int]] = []
    known: list[tuple[str, ...]] = []
    p = 0
    while p < n:
        matched = next(
            (len(kb) for kb in sorted(known, key=len, reverse=True) if tuple(toks[p : p + len(kb)]) == kb),
            0,
        )
        if matched:
            end = p + matched
        else:
            best = longest_repeat_at(p)
            if best >= _MIN_REPEAT:
                end = p + best
            else:
                end = next((b for b in bounds if b > p), n)
            known.append(tuple(toks[p:end]))
        blocks.append((p, end))
        p = end

    # refinement: split any block containing another known block as a strict
    # prefix/suffix, so occurrences of the same section align across the stream
    def split_pass(blocks: list[tuple[int, int]]) -> tuple[list[tuple[int, int]], bool]:
        tuples = {tuple(toks[a:b]) for a, b in blocks}
        out: list[tuple[int, int]] = []
        changed = False
        for a, b in blocks:
            t = tuple(toks[a:b])
            # a section printed as an immediate doubled repeat ("C C") with no solo
            # occurrence tiles as one double-length block — split it at the midpoint
            half = len(t) // 2
            if len(t) % 2 == 0 and half >= _MIN_REPEAT and t[:half] == t[half:]:
                out += [(a, a + half), (a + half, b)]
                changed = True
                continue
            for other in sorted(tuples - {t}, key=len, reverse=True):
                length = len(other)
                if length < _MIN_REPEAT:
                    # never split on a 1-line block (a trailing echo of a section's
                    # last line) — that's what fragments a shared refrain line into
                    # 1-line cards across the whole stream
                    continue
                if length < len(t) and t[:length] == other:
                    out += [(a, a + length), (a + length, b)]
                    changed = True
                    break
                if length < len(t) and t[-length:] == other:
                    out += [(a, b - length), (b - length, b)]
                    changed = True
                    break
            else:
                out.append((a, b))
        return out, changed

    for _ in range(4):
        blocks, changed = split_pass(blocks)
        if not changed:
            break
    return blocks


def _tiling_blocks(work: list[str]) -> tuple[list[int], list[list[str]]]:
    toks = [_norm(x) for x in work]
    keys: list[tuple[str, ...]] = []
    cards: list[list[str]] = []
    seq: list[int] = []
    for a, b in _segment(toks):
        t = tuple(toks[a:b])
        if t in keys:
            seq.append(keys.index(t))
        else:
            keys.append(t)
            cards.append(work[a:b])
            seq.append(len(cards) - 1)
    return seq, cards


def flatten(sections: list[dict]) -> list[str]:
    """Sections -> the blank-line-separated ``Song.lines`` mirror (transcribe.Song)."""
    flat: list[str] = []
    for sec in sections:
        if flat:
            flat.append("")
        flat.extend(sec["lines"])
    return flat


def suggest(lines: list[str]) -> tuple[list[dict], str] | None:
    """Suggest ``(sections, arrangement)`` for a canonical lyric text.

    ``sections`` are deduped ``{"label", "lines"}`` cards in first-occurrence
    order; ``arrangement`` is the block sequence in page order (``"V1 C V1 C C"``),
    which reproduces the original stream through ``arranged_chunks()``. Returns
    None when no multi-line block repeats — the caller keeps the song unlabeled.

    Labels: the most-repeated multi-line block is C (ties prefer a block that
    doesn't open the song); other repeated multi-line blocks first appearing
    after C are B, B2…; a short one-off (or single-line) block closing the
    stream is TAG; the rest are V1, V2… in page order. A song that is one block
    repeated (a short call-to-worship printed per key) is V1, not C.
    """
    stanzas = _split_stanzas(lines)
    if not stanzas:
        return None
    if len(stanzas) >= 2:
        seq, cards = _stanza_blocks(stanzas)
    else:
        seq, cards = _tiling_blocks(stanzas[0])

    count = [seq.count(i) for i in range(len(cards))]
    if len(stanzas) < 2:
        # tiling gate: a card under 2 lines means the repetition is a shared refrain
        # line / per-verse hymn refrain / substitution verse, not section structure —
        # every mislabeled sheet in the 8-week eval had one. The only trusted shape is
        # a lone trailing echo of a section's last line (single occurrence, closing
        # the stream), which labels TAG.
        for i, card in enumerate(cards):
            if len(card) < 2 and not (count[i] == 1 and seq[-1] == i):
                return None
    big = [i for i in range(len(cards)) if len(cards[i]) >= 2]
    repeated_big = [i for i in big if count[i] >= 2]
    if not repeated_big:
        return None  # no repeated multi-line block — structure unrecoverable from text

    chorus = max(repeated_big, key=lambda i: (count[i], i > 0)) if len(big) > 1 else None
    final = seq[-1]
    labels: dict[int, str] = {}
    v = b_ = 0
    for i in range(len(cards)):
        if (
            i == final
            and i != chorus
            and len(cards) > 1
            and len(cards[i]) <= 2
            and (count[i] == 1 or len(cards[i]) == 1)
        ):
            labels[i] = "TAG"
        elif i == chorus:
            labels[i] = "C"
        elif i in repeated_big and chorus is not None and i > chorus:
            b_ += 1
            labels[i] = "B" if b_ == 1 else f"B{b_}"
        else:
            v += 1
            labels[i] = f"V{v}"

    sections = [{"label": labels[i], "lines": list(cards[i])} for i in range(len(cards))]
    return sections, " ".join(labels[i] for i in seq)
