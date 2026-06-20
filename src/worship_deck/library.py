"""Persistent confession-song library: reusable 고백의 찬양 lyrics across weeks.

고백의 찬양 rotates between a handful of songs. Transcribing + polishing the same lyrics
every week is wasted work, so a polished `Song` is saved here once (keyed by a slug derived
from its title) and later picked from the home screen instead of re-uploading the sheet image.

Unlike `store.py` (per-date run files), this is a flat, non-date-keyed store: one JSON file
per song under the git-ignored data/library/confession/ tree. It survives the new-week inbox
reset, which only clears data/inbox/. A song is the same `{title, lines, composer}` dict shape
as `ServiceData.confession_song` (lyrics/transcribe.py:Song).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

# Where saved confession songs live (git-ignored). Tests monkeypatch this.
LIBRARY_DIR = Path("data/library/confession")

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


def _path_for(slug: str) -> Path:
    """Return the file path for a slug, rejecting anything that could traverse the tree."""
    if not _SAFE_SLUG.fullmatch(slug):
        raise ValueError(f"unsafe library slug: {slug!r}")
    return LIBRARY_DIR / f"{slug}.json"


def save_song(song: dict) -> str:
    """Save a `{title, lines, composer}` song; return its slug. Re-saving overwrites."""
    title = (song.get("title") or "").strip()
    if not title:
        raise ValueError("song needs a title to save to the library")
    slug = _slug(title)
    payload = {
        "title": title,
        "lines": list(song.get("lines") or []),
        "composer": song.get("composer") or "",
    }
    dest = _path_for(slug)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return slug


def list_songs() -> list[dict]:
    """All saved songs as `{slug, title, composer}`, sorted by title (for the picker)."""
    out: list[dict] = []
    for f in LIBRARY_DIR.glob("*.json"):
        song = json.loads(f.read_text(encoding="utf-8"))
        out.append({"slug": f.stem, "title": song.get("title", ""), "composer": song.get("composer", "")})
    return sorted(out, key=lambda s: s["title"])


def load_song(slug: str) -> dict | None:
    """Return the full `{title, lines, composer}` song for a slug, or None if absent."""
    path = _path_for(slug)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
