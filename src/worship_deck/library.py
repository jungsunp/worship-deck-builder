"""Persistent song library: reusable confession and worship lyrics across weeks.

고백의 찬양 rotates between a handful of songs. Transcribing + polishing the same lyrics
every week is wasted work, so a polished `Song` is saved here once (keyed by a slug derived
from its title) and later picked from the home screen instead of re-uploading the sheet image.

Unlike `store.py` (per-date run files), this is a flat, non-date-keyed store: one JSON file
per song under the git-ignored data/library/confession/ tree. It survives the new-week inbox
reset, which only clears data/inbox/. A song is the same `{title, lines, composer, sections,
arrangement}` dict shape as `ServiceData.confession_song` (lyrics/transcribe.py:Song).

A second library, ``data/library/worship/`` (#204), holds the 찬양 medley and 설교후 찬양 songs
the operator has confirmed in review. Unlike the confession library it is not picked by hand:
``match_worship`` is consulted at assemble, before the gasazip lookup, and returns a song when
the sheet's OCR fragments / title match it. The play order changes weekly, so the stored
``arrangement`` is kept for reference but never reused.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

from worship_deck.lyrics import online

# Where saved confession songs live (git-ignored). Tests monkeypatch this.
LIBRARY_DIR = Path("data/library/confession")
# Where saved worship (찬양 / 설교후 찬양) songs live (#204). Tests monkeypatch this too.
WORSHIP_DIR = Path("data/library/worship")

# Slug chars allowed in a filename stem: word chars + Hangul, joined by single hyphens.
_SLUG_RE = re.compile(r"[^\w가-힣]+")
# What a stored filename stem is allowed to be (blocks path traversal on load).
_SAFE_SLUG = re.compile(r"[\w가-힣-]+")


def _slug(title: str) -> str:
    """Derive a filesystem-safe stem from a song title, keeping Hangul.

    Falls back to a short hash when the title has no slug-able characters, so a song is
    never lost to an empty filename.
    """
    slug = _SLUG_RE.sub("-", title).strip("-").lower()
    return slug or "song-" + hashlib.sha1(title.encode("utf-8")).hexdigest()[:8]


def _path_for(slug: str, directory: Path | None = None) -> Path:
    """Return the file path for a slug, rejecting anything that could traverse the tree."""
    if not _SAFE_SLUG.fullmatch(slug):
        raise ValueError(f"unsafe library slug: {slug!r}")
    return (LIBRARY_DIR if directory is None else directory) / f"{slug}.json"


def save_song(song: dict, directory: Path | None = None) -> str:
    """Save a `{title, lines, composer, sections, arrangement}` song; return its slug.

    Re-saving overwrites. `sections`/`arrangement` may be absent (legacy/typed songs).
    `directory` defaults to the confession library; pass `WORSHIP_DIR` for worship songs.
    """
    title = (song.get("title") or "").strip()
    if not title:
        raise ValueError("song needs a title to save to the library")
    slug = _slug(title)
    payload = {
        "title": title,
        "lines": list(song.get("lines") or []),
        "composer": song.get("composer") or "",
        # Operator-labeled V1/C/B section cards + 진행순서 play-order, persisted so a picked
        # song comes back pre-split next week instead of being re-labeled from scratch.
        "sections": list(song.get("sections") or []),
        "arrangement": song.get("arrangement") or "",
    }
    dest = _path_for(slug, directory)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return slug


def list_songs(directory: Path | None = None) -> list[dict]:
    """All saved songs as `{slug, title, composer}`, sorted by title (for the picker)."""
    out: list[dict] = []
    for f in (LIBRARY_DIR if directory is None else directory).glob("*.json"):
        song = json.loads(f.read_text(encoding="utf-8"))
        out.append({"slug": f.stem, "title": song.get("title", ""), "composer": song.get("composer", "")})
    return sorted(out, key=lambda s: s["title"])


def load_song(slug: str, directory: Path | None = None) -> dict | None:
    """Return the full song dict for a slug, or None if absent.

    Newer entries carry `sections`/`arrangement`; legacy ones have only title/lines/composer.
    """
    path = _path_for(slug, directory)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def match_worship(titles: list[str], fragments: list[str]) -> tuple[dict, float, float] | None:
    """Find the saved worship song a sheet is, or None (#204). Runs before the gasazip lookup.

    Scores every stored song exactly like ``online.lookup`` scores a gasazip candidate: the OCR
    fragments' Hangul bigrams against the song's lyric bigrams (``cand_cov`` = share of the
    song's bigrams the sheet covers, ``ocr_cov`` = share of the sheet's bigrams the song
    covers), accepted at ``online._MATCH_THRESHOLD`` or — when one of the detected ``titles``
    resembles the song's — at ``online._OCR_COV_MIN``. Matching by fragments, not only title,
    catches sheets titled by their first line (#201). Returns ``(song, cand_cov, ocr_cov)`` for
    the best accepted song (the stored dict plus its ``slug``).
    """
    ocr = online._bigrams("".join(fragments))
    best: tuple[dict, float, float] | None = None
    for f in sorted(WORSHIP_DIR.glob("*.json")):
        try:
            song = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # one unreadable file must not block the assemble
        lines = song.get("lines") or []
        cand_cov, ocr_cov = online._covs(ocr, lines)
        similar = any(online._title_similar(t, song.get("title", "")) for t in titles)
        accepted = cand_cov >= online._MATCH_THRESHOLD or (similar and ocr_cov >= online._OCR_COV_MIN)
        if accepted and (best is None or cand_cov > best[1]):
            best = ({**song, "slug": f.stem}, cand_cov, ocr_cov)
    return best


# ── backfill ─────────────────────────────────────────────────────────────────


def backfill_worship(runs_dir: Path, write: bool = False) -> list[tuple[str, str, str]]:
    """Collect worship songs from past reviewed runs into the worship library (#204).

    Walks ``runs_dir/*.json`` oldest first so a song sung in several weeks ends up with its
    newest text. Takes every 찬양 medley song and the 설교후 찬양 that has a title and lyrics
    **and** whose provenance says the text is canonical (``gasazip`` or ``library``): runs from
    before provenance existed (May–July 2026) hold OCR-era text with typos and placeholder
    titles, which would poison later matches — those songs enter by being saved in review.
    Returns ``(run date, title, slug)`` per song; with ``write=False`` nothing is saved.
    """
    found: dict[str, tuple[str, dict]] = {}
    for f in sorted(runs_dir.glob("????-??-??.json")):
        try:
            run = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        songs = list(run.get("worship_songs") or []) + [run.get("worship_after_sermon") or {}]
        for song in songs:
            canonical = (song.get("provenance") or {}).get("source") in ("gasazip", "library")
            if canonical and (song.get("title") or "").strip() and any(
                (ln or "").strip() for ln in song.get("lines") or []
            ):
                found[_slug(song["title"].strip())] = (f.stem, song)
    out = []
    for slug, (date, song) in sorted(found.items()):
        if write:
            save_song(song, WORSHIP_DIR)
        out.append((date, song["title"].strip(), slug))
    return out


if __name__ == "__main__":
    if sys.argv[1:2] != ["backfill"]:
        sys.exit("usage: python -m worship_deck.library backfill [RUNS_DIR] [--write]")
    rest = [a for a in sys.argv[2:] if a != "--write"]
    done = backfill_worship(Path(rest[0] if rest else "data/runs"), write="--write" in sys.argv)
    for date, title, slug in done:
        print(f"{date}  {title}  → {WORSHIP_DIR / (slug + '.json')}")
    print(f"{len(done)} song(s) {'saved' if '--write' in sys.argv else '(dry run — add --write to save)'}")
