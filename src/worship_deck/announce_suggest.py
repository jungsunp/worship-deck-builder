"""Deterministic half of ``/prep-week``'s 교회소식 step: Claude's wording fixes → review suggestions.

After the lyric step, Claude reads the week's announcements as ``show`` prints them (wrapped the
way the slide wraps them at 80pt, with the size the Keynote build would give each item) and
writes a spec of small find/replace edits per item, each of one kind:

- ``typo``: Korean spelling, spacing and number slips carried over from the bulletin;
- ``break``: line breaks: join a sentence the bulletin broke, break a title or phrase that the
  slide would otherwise wrap mid-phrase;
- ``shorten``: tighter wording for an item that won't fit its box at 80pt (many members are
  elders: a shorter item beats a smaller font);
- ``style``: formatting the assemble rules leave to the operator, because their choice varies
  week to week (``시간:``/``장소:`` lines, where ``(문의 …)`` goes). Review's 모두 적용 skips these.

This module checks that each edit's ``old`` text occurs exactly once in its item, measures the
items with the Keynote build's own fit maths, and stores the edits under ``announcements`` in
the ``data/runs/<date>.suggest.json`` sidecar, never in the run file. Review offers each edit
with 적용, and the operator saves as usual.

CLI (what the skill runs)::

    python -m worship_deck.announce_suggest show DATE
    python -m worship_deck.announce_suggest apply DATE SPEC.json
"""

from __future__ import annotations

import difflib
import json
import re
import subprocess
import sys
from pathlib import Path

from worship_deck import store
from worship_deck.keynote import build as keynote
from worship_deck.lyrics import suggest

KINDS = ("typo", "break", "shorten", "style")
# master.key's shortest 교회소식 item box: (width, height, font, base pt). The build reads each
# slide's real box, and items past the template's own slides get its first, taller box, so
# measuring every item against the shortest one errs toward flagging.
BOX = (1876, 887, "NanumGothicBold", 80)
_WRAP_LINES = Path(keynote.__file__).with_name("wrap_lines.swift")
_CTX = 12  # characters of context review shows either side of an edit


def fit_pts(items: list[str]) -> list[int]:
    """The size the Keynote build would give each item in BOX (its own fit maths); BOX's base
    size when the item fits or can't be measured (no ``swift``)."""
    if not items:
        return []
    return [pt or BOX[3] for pt in keynote._fit_announcement_sizes(items, [BOX] * len(items))]


def max_lines(pt: int) -> int:
    """How many lines BOX holds at ``pt`` (the build's height formula, solved for lines)."""
    return int((BOX[1] + keynote._ANNOUNCE_TRIM * pt) // (keynote._ANNOUNCE_LINE_H * pt))


def wrap(items: list[str], pt: int) -> list[list[str]]:
    """Each item's lines as the slide wraps them at ``pt`` (CoreText, like the build's measure).
    A line ending in "\\n" ends a paragraph; any other but the last is a soft wrap. Without
    ``swift`` or the font, only the hard breaks."""
    requests = [
        {"text": t, "font": BOX[2], "size": pt, "width": BOX[0] - keynote._ANNOUNCE_INSET_W}
        for t in items
    ]
    try:
        out = json.loads(subprocess.run(
            ["swift", str(_WRAP_LINES)], input=json.dumps(requests),
            capture_output=True, text=True, timeout=120, check=True,
        ).stdout)
    except FileNotFoundError:
        out = [None] * len(items)
    return [ls if ls is not None else [ln + "\n" for ln in t.split("\n")] for t, ls in zip(items, out)]


def resolve(text: str, old: str) -> tuple[int, int] | str:
    """The span of ``old`` in ``text``: an exact match, else one where each run of whitespace in
    ``old`` may be any whitespace (a line break read as a space, or the reverse). An error
    message when it's missing or not unique."""
    hits = [m.span() for m in re.finditer(re.escape(old), text)] if old else []
    if not hits and old.split():
        hits = [m.span() for m in re.finditer(r"\s+".join(map(re.escape, old.split())), text)]
    if len(hits) == 1:
        return hits[0]
    return f"{len(hits)}군데 있음 — 앞뒤 글자를 더 넣으세요" if hits else "항목에 없음"


def char_diff(old: str, new: str) -> list[list[str]]:
    """Character diff for review: ``[[op, text], …]``, op "=" kept, "-" removed, "+" added."""
    out: list[list[str]] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == "equal":
            out.append(["=", old[i1:i2]])
            continue
        if i2 > i1:
            out.append(["-", old[i1:i2]])
        if j2 > j1:
            out.append(["+", new[j1:j2]])
    return out


def apply_edits(text: str, edits: list[dict], kinds: tuple[str, ...] = KINDS) -> str:
    """``text`` with the given kinds of (resolved, non-overlapping) edits applied."""
    for e in sorted((e for e in edits if e["kind"] in kinds), key=lambda e: -e["span"][0]):
        a, b = e["span"]
        text = text[:a] + e["new"] + text[b:]
    return text


def check_item(text: str, item: int, edits: list[dict]) -> tuple[list[dict], list[str]]:
    """Resolve one item's spec edits against its text: ``(edits in text order, errors)``.
    Each kept edit carries its exact ``old``, its span, context and a character diff."""
    kept: list[dict] = []
    errors: list[str] = []
    for e in edits:
        old, new, kind = e.get("old", ""), e.get("new", ""), e.get("kind")
        if kind not in KINDS:
            errors.append(f"[{item}] kind {kind!r}: {' / '.join(KINDS)} 중 하나")
            continue
        span = resolve(text, old)
        if isinstance(span, str):
            errors.append(f"[{item}] {old!r}: {span}")
            continue
        if any(span[0] < k["span"][1] and k["span"][0] < span[1] for k in kept):
            errors.append(f"[{item}] {old!r}: 다른 수정과 겹침 — 하나로 합치세요")
            continue
        a, b = span
        if text[a:b] == new:
            errors.append(f"[{item}] {old!r}: 바뀌는 것이 없음")
            continue
        kept.append({
            "kind": kind, "old": text[a:b], "new": new, "why": e.get("why", ""),
            "span": [a, b], "ctx": [text[max(0, a - _CTX):a], text[b:b + _CTX]],
            "diff": char_diff(text[a:b], new),
        })
    return sorted(kept, key=lambda k: k["span"][0]), errors


def build_suggestions(items: list[str], spec: dict) -> tuple[list[dict], list[str]]:
    """Spec ``{"announcements": [{"item": n, "edits": [...]}, ...]}`` (1-based ``item``) →
    the sidecar records and the error/warning lines for the report."""
    records: list[dict] = []
    errors: list[str] = []
    for entry in spec.get("announcements", []):
        n = int(entry["item"])
        if not 1 <= n <= len(items):
            errors.append(f"item {n}: 교회소식은 {len(items)}개")
            continue
        edits, errs = check_item(items[n - 1], n, entry.get("edits", []))
        errors += errs
        if edits:
            records.append({"item": n, "title": items[n - 1].split("\n")[0], "edits": edits})
    before = fit_pts(items)
    after = list(items)
    for r in records:  # 모두 적용: every kind but the operator's own formatting choices
        after[r["item"] - 1] = apply_edits(items[r["item"] - 1], r["edits"], ("typo", "break", "shorten"))
    after_pts = fit_pts(after)
    for r in records:
        r["pt"], r["pt_after"] = before[r["item"] - 1], after_pts[r["item"] - 1]
    for n, (pt, pt_after) in enumerate(zip(before, after_pts), 1):
        if pt_after < BOX[3]:
            why = "제안 때문에" if pt >= BOX[3] else "제안 적용 후에도"
            errors.append(f"⚠ [{n}] {why} {BOX[3]}pt에 안 들어감 → 빌드가 {pt_after}pt로 줄임")
    return records, errors


def apply_spec(service_date: str, spec: dict) -> tuple[list[dict], list[str]]:
    """Check ``spec`` against the stored run and write its edits into the sidecar."""
    records, errors = build_suggestions(store.load(service_date).announcements, spec)
    suggest.save_section(service_date, "announcements", records)
    return records, errors


# ── CLI ───────────────────────────────────────────────────────────────────────


def _show(service_date: str) -> None:
    items = store.load(service_date).announcements
    base = BOX[3]
    print(f"교회소식 {len(items)}개 — {base}pt 기준 줄바꿈 (↩ = 슬라이드가 자동으로 넘기는 곳, 글에는 없음)")
    for n, (text, pt, lines) in enumerate(zip(items, fit_pts(items), wrap(items, base)), 1):
        head = f"[{n}] {len(lines)}/{max_lines(base)}줄"
        if pt < base:
            head += f" ⚠ {base}pt에 안 들어감 → 빌드가 {pt}pt로 줄임 (shorten 제안 필요)"
        print(head)
        for i, ln in enumerate(lines):
            soft = not ln.endswith("\n") and i < len(lines) - 1
            print("    " + ln.rstrip("\n") + (" ↩" if soft else ""))


def _report(service_date: str, records: list[dict], errors: list[str]) -> None:
    print(f"wrote {suggest.sidecar_path(service_date)} — {len(records)}개 항목, "
          f"{sum(len(r['edits']) for r in records)}개 수정")
    for r in records:
        print(f"[{r['item']}] {r['title']}  {r['pt']}pt → {r['pt_after']}pt")
        for e in r["edits"]:
            old, new = (s.replace("\n", "⏎") for s in (e["old"], e["new"]))
            print(f"    {e['kind']:<7} {old!r} → {new!r}  {e['why']}")
    for line in errors:
        print(line if line.startswith("⚠") else f"✗ {line}")


def main(argv: list[str]) -> int:
    cmd, args = (argv[0], argv[1:]) if argv else ("", [])
    if cmd == "show" and len(args) == 1:
        _show(args[0])
    elif cmd == "apply" and len(args) == 2:
        spec = json.loads(Path(args[1]).read_text(encoding="utf-8"))
        _report(args[0], *apply_spec(args[0], spec))
    else:
        print(__doc__.split("CLI (what the skill runs)::")[1], file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
