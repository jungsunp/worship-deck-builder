"""Deterministic half of the ``/prep-week`` skill: Claude-read sheet marks → review suggestions (#209).

The operator runs ``/prep-week <date>`` in their own Claude Code session after assemble. Claude
reads each band lead sheet with its own vision (title, red V/C/B letters and where they sit,
×N repeats, X-outs, segues) and writes a small *spec* per song: which gasazip song, where each
labeled section starts (a lyric anchor or a canonical line number), and the play order. This
module does everything else, so Claude never types slide text:

- candidates and canonical lyrics come from gasazip (``online``), re-broken like assemble does;
- anchors are mapped onto the canonical lines by bigram overlap (``online._bigrams``), scanning
  forward so identical verse openers ("주의 자녀로 산다는 것은" ×4) land on successive verses;
- the play order is expanded (``Cx3`` → ``C C C``, via ``transcribe.parse_arrangement``) and every
  label is checked against the sections.

The result goes to a sidecar ``data/runs/<date>.suggest.json`` — never the run file, which every
review save replaces wholesale (``PUT /runs``). Review shows a "Claude 제안" block per song with
an apply button; nothing is applied silently. Top-level keys are per review section
(``worship_songs`` today) so other sections can join later.

No API key, no network beyond gasazip: weeks without a Claude session simply have no sidecar.

CLI (what the skill runs)::

    python -m worship_deck.lyrics.suggest show DATE
    python -m worship_deck.lyrics.suggest search DATE REF "제목"
    python -m worship_deck.lyrics.suggest lines SONG_ID
    python -m worship_deck.lyrics.suggest apply DATE SPEC.json
"""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from worship_deck import store
from worship_deck.lyrics import linebreak, online, sections, transcribe

_ANCHOR_MIN = 0.6  # share of the anchor's bigrams the start window must contain
_OWN_MIN = 0.5  # share of the start line's own bigrams found in the anchor
_TIE = 0.05  # scores this close to the best count as a tie (earliest wins)


def sidecar_path(service_date: str) -> Path:
    """``data/runs/<date>.suggest.json`` (validates the date like the run file)."""
    return store.path_for(service_date).with_suffix(".suggest.json")


def load_sidecar(service_date: str) -> dict | None:
    p = sidecar_path(service_date)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# Hymn pages mark verses and refrains inline ("1.죄에서 …", "{후렴}내가 믿고 …") — page
# furniture, not lyrics, and it would land on the slide.
_VERSE_NO = re.compile(r"^\s*\d+\s*\.?\s*(?=[가-힣])")
_MARKER = re.compile(r"\{[^}]*\}")


def canonical_lines(song_id: str, title: str = "", artist: str = "") -> list[str]:
    """A gasazip song's lyric lines exactly as assemble would store them (header-stripped,
    re-broken to the lyric banner), minus inline verse numbers and ``{후렴}`` markers.
    Raises ``httpx.HTTPError`` on network failure."""
    cand = online.Candidate(song_id=song_id, title=title, artist=artist)
    cand.lines = online.fetch_lyrics(song_id)
    if title and artist:  # an empty title/artist "matches" any first line and would drop it
        online._strip_header(cand)
    return linebreak.rebreak([_MARKER.sub("", _VERSE_NO.sub("", ln)).strip() for ln in cand.lines])


def _cover(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a) if a else 0.0


def locate(lines: list[str], anchor: str | int, after: int = -1) -> tuple[int, float]:
    """Index of the canonical line where ``anchor`` starts, and the match score (0..1).

    An int anchor is a line number taken as-is. A text anchor (lyric as read off the sheet —
    syllable spacing and line breaks don't matter) is scored at every non-blank line: ``s``,
    the share of its bigrams inside that line's two-line window, and ``t``, the share of the
    line's own bigrams inside the anchor (so a window starting a line early doesn't win).
    Past ``after``, among lines with ``t`` >= _OWN_MIN, the best ``s`` wins, then the best ``t``,
    and remaining ties go to the earliest — so identical verse openers land on successive verses in spec order. With no
    acceptable line there it falls back to the best window anywhere; callers warn on a low score.
    """
    if isinstance(anchor, int):
        return (anchor, 1.0) if 0 <= anchor < len(lines) and lines[anchor].strip() else (-1, 0.0)
    a = online._bigrams(anchor)
    content = [i for i, ln in enumerate(lines) if ln.strip()]
    scored = []  # (i, s, t)
    for k, i in enumerate(content):
        nxt = lines[content[k + 1]] if k + 1 < len(content) else ""
        scored.append((i, _cover(a, online._bigrams(lines[i] + nxt)), _cover(online._bigrams(lines[i]), a)))
    ahead = [x for x in scored if x[0] > after and x[2] >= _OWN_MIN]
    if ahead and max(x[1] for x in ahead) >= _ANCHOR_MIN:
        top = max(x[1] for x in ahead)
        near = [x for x in ahead if x[1] >= top - _TIE]
        own = max(x[2] for x in near)  # "구원을/능력을" share a prefix: the line that IS the anchor wins
        i, s, _ = next(x for x in near if x[2] >= own - _TIE)
        return i, s
    if not scored:
        return -1, 0.0
    i, s, _ = max(scored, key=lambda x: x[1] + x[2])
    return i, s


def _trim(block: list[str]) -> list[str]:
    while block and not block[0].strip():
        block = block[1:]
    while block and not block[-1].strip():
        block = block[:-1]
    return block


def map_sections(lines: list[str], spec: list[dict]) -> tuple[list[dict], list[str]]:
    """Spec entries ``{"label", "at", "end"?}`` → ``({"label","lines"}, warnings)``.

    Each entry starts at its ``at`` anchor and runs to the line before the next entry's start
    (or to its own ``end`` anchor, inclusive). Entries are given in canonical-text order; a
    label listed again is just a boundary (the chorus printed after every verse) — the first
    occurrence defines the card. Canonical text before the first anchor (credits, an intro
    the sheet skips) is left out. Nothing is halved automatically: a page that prints a section
    twice is either a repeat (cut it with ``end``) or a written-out double the deck shows whole
    (나는 찬양하리라, 2026-11-01) — only the sheet tells which.
    """
    warnings: list[str] = []
    starts: list[int] = []
    after = -1
    for e in spec:
        i, score = locate(lines, e["at"], after)
        if i < 0:
            warnings.append(f"{e['label']}: 시작 위치를 찾지 못함 ({e['at']!r})")
        elif score < _ANCHOR_MIN:
            warnings.append(f"{e['label']}: 시작 위치 불확실 (일치 {score:.0%}, {e['at']!r})")
        starts.append(i)
        after = max(after, i)
    cards: list[dict] = []
    seen: set[str] = set()
    for k, e in enumerate(spec):
        a = starts[k]
        label = str(e["label"]).strip()
        if a < 0 or label.upper() in seen:
            continue
        later = [s for s in starts if s > a]
        b = min(later) if later else len(lines)
        if "end" in e:
            j, _ = locate(lines, e["end"], a - 1)
            if j >= a:
                b = min(b, j + 1)
            else:
                warnings.append(f"{label}: 끝 위치를 찾지 못함 ({e['end']!r})")
        block = _trim(lines[a:b])
        if not block:
            warnings.append(f"{label}: 빈 구간")
            continue
        seen.add(label.upper())
        cards.append({"label": label, "lines": block})
    # A card that runs into the opening two lines of itself or another card usually swallowed
    # a repeat or the next section (the last entry runs to the end of the text): cut it with
    # `end` or list the next section, unless the sheet really writes it out. Two lines, so a
    # refrain like "내 삶에 내 삶에" ×2 doesn't trip it.
    keys = [[sections._norm(x) for x in c["lines"] if x.strip()] for c in cards]
    for c, k in zip(cards, keys, strict=True):
        for other, ok in zip(cards, keys, strict=True):
            head = ok[:2]
            if len(head) == 2 and any(k[i : i + 2] == head for i in range(2 if other is c else 1, len(k) - 1)):
                warnings.append(f"{c['label']}: {other['label']}의 첫 두 줄이 구간 안에 있음 — end로 자르거나 구간을 나누세요")
                break
    return cards, warnings


def expand_arrangement(arrangement: str, cards: list[dict]) -> tuple[str, list[str]]:
    """Sheet-style play order → the stored one-label-per-play string, plus unknown-label warnings."""
    known = {c["label"].upper(): c["label"] for c in cards}
    seq, unknown = [], []
    for tok in transcribe.parse_arrangement(arrangement):
        if tok.upper() in known:
            seq.append(known[tok.upper()])
        elif tok not in unknown:
            unknown.append(tok)
    warnings = [f"진행 순서에 없는 구간 라벨: {', '.join(unknown)}"] if unknown else []
    if not seq:
        warnings.append("진행 순서가 비어 있음")
    return " ".join(seq), warnings


def build_song(spec: dict, run_song: dict) -> dict:
    """One spec entry → its sidecar record (see module docstring)."""
    out = {"ref": spec["ref"], "run_title": run_song.get("title", "")}
    for k in ("sheets", "marks", "note", "confidence", "continuation_of"):
        if k in spec:
            out[k] = spec[k]
    if "continuation_of" in spec:
        return out  # a continuation page / intro strip: note only, nothing to apply
    prov = run_song.get("provenance") or {}
    if not spec.get("song_id"):
        if prov.get("source") == "library" and run_song.get("sections") and spec.get("arrangement"):
            # Library hit (#204): assemble used the operator-confirmed lines and section labels, so
            # the sheet only has to give this week's play order — no gasazip, no anchors.
            cards = [{"label": c["label"], "lines": list(c["lines"])} for c in run_song["sections"]]
            arrangement, warnings = expand_arrangement(spec["arrangement"], cards)
            out.update(title=run_song.get("title", ""), sections=cards, lines=sections.flatten(cards),
                       arrangement=arrangement, warnings=warnings)
        return out  # otherwise no song: note only, nothing to apply
    same = str(prov.get("song_id", "")) == str(spec["song_id"])
    title = spec.get("title") or (run_song.get("title", "") if same else "")
    artist = spec.get("artist") or (prov.get("artist", "") if same else "")
    lines = canonical_lines(str(spec["song_id"]), title, artist)
    cards, warnings = map_sections(lines, spec.get("sections", []))
    arrangement, arr_warn = expand_arrangement(spec.get("arrangement", ""), cards)
    out.update(
        song_id=str(spec["song_id"]),
        title=title,
        artist=artist,
        sections=cards,
        lines=sections.flatten(cards),
        arrangement=arrangement,
        warnings=warnings + arr_warn,
    )
    return out


def apply_spec(service_date: str, spec: dict) -> dict:
    """Build every song in ``spec`` against the stored run and write the sidecar."""
    run = store.load(service_date)
    songs = []
    for s in spec.get("worship_songs", []):
        ref = int(s["ref"])
        if not 0 <= ref < len(run.worship_songs):
            raise ValueError(f"ref {ref}: run has {len(run.worship_songs)} worship songs")
        songs.append(build_song(s, run.worship_songs[ref]))
    doc = {
        "version": 1,
        "date": service_date,
        "created": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
        "worship_songs": songs,
    }
    p = sidecar_path(service_date)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return doc


# ── CLI ───────────────────────────────────────────────────────────────────────


def _show(service_date: str) -> None:
    print("sheets (assemble's order):")
    for p in sorted(Path("data/inbox").glob("sheet-*")):
        print(f"  {p}")
    run = store.load(service_date)
    print("run worship_songs:")
    for i, s in enumerate(run.worship_songs):
        prov = s.get("provenance") or {}
        print(f"  ref {i}: {s.get('title')!r} source={prov.get('source')} "
              f"song_id={prov.get('song_id', '')} slug={prov.get('slug', '')} merged_sheets={prov.get('merged_sheets', 1)} "
              f"cand_cov={prov.get('cand_cov', 0):.2f}")
        print(f"    sections={[c['label'] for c in s.get('sections', [])]} "
              f"arrangement={s.get('arrangement', '')!r}")
        for c in s.get("candidates", [])[:5]:
            print(f"    candidate {c['song_id']} {c['title']!r} / {c['artist']} cov={c['cand_cov']:.2f}")


def _search(service_date: str, ref: int, title: str) -> None:
    run = store.load(service_date)
    fragments = run.worship_songs[ref].get("fragments", []) if ref < len(run.worship_songs) else []
    for c in online.search_scored(title, fragments):
        prev = " / ".join([ln for ln in c.lines if ln.strip()][:2])
        print(f"{c.song_id} {c.title!r} / {c.artist} cov={c.cand_cov:.2f}/{c.ocr_cov:.2f} | {prev}")


def _lines(song_id: str) -> None:
    lines = canonical_lines(song_id)
    for i, ln in enumerate(lines):
        print(f"{i:3d} {ln}" if ln.strip() else f"{i:3d} ──")
    auto = sections.suggest(lines)
    if auto:
        print(f"(#206 auto-structure: {auto[1]})")


def main(argv: list[str]) -> int:
    cmd, args = (argv[0], argv[1:]) if argv else ("", [])
    if cmd == "show" and len(args) == 1:
        _show(args[0])
    elif cmd == "search" and len(args) == 3:
        _search(args[0], int(args[1]), args[2])
    elif cmd == "lines" and len(args) == 1:
        _lines(args[0])
    elif cmd == "apply" and len(args) == 2:
        doc = apply_spec(args[0], json.loads(Path(args[1]).read_text(encoding="utf-8")))
        print(f"wrote {sidecar_path(args[0])}")
        for s in doc["worship_songs"]:
            print(f"ref {s['ref']}: {s.get('title') or s['run_title']!r}")
            if "continuation_of" in s or "sections" not in s:
                print(f"  (note only) {s.get('note', '')}")
                continue
            for c in s["sections"]:
                print(f"  {c['label']}: {' / '.join(ln for ln in c['lines'] if ln.strip())}")
            print(f"  arrangement: {s['arrangement']}")
            for w in s["warnings"]:
                print(f"  ⚠ {w}")
    else:
        print(__doc__.split("CLI (what the skill runs)::")[1], file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
