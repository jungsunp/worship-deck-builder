"""Pack a generated ``.pro`` plus the media it references into a ``.probundle`` (#236).

A ``.pro`` is a bare serialized ``rv.data.Presentation``: it **cannot embed media**, only
reference it by absolute ``file://`` URL. The weekly deck carries the church logo, the two
pre-service photos and one image per 봉헌 hymn page (#179), so the ``.pro`` on its own only opens
on the machine that built it. The deck has to reach another church member as **one file** they
import on the church Mac, which is exactly what ProPresenter's own Export → bundle produces.

Anatomy, read off a hand-export of the #178 deck — a **zip64 archive, every entry stored**
(``method=0``, no compression)::

    /Users/…/propresenter/assets/npc-logo.png   <- media, keyed by its ABSOLUTE source path
    주일예배 2026-08-30.pro                       <- the .pro, at the archive root

The ``.pro`` inside keeps its **untouched** ``file:///Users/…`` URLs; ProPresenter rewrites them
on *import* by joining zip entry name -> media URL. So the entry name is load-bearing, and there
is no manifest — the names alone are the mapping.

Two quirks of ProPresenter's own writer, neither of which we copy:

* Its central-directory size counts the trailing EOCD records (98 bytes too long), so ``unzip``
  warns and Python's ``zipfile`` refuses to open it outright. Its *reader* is evidently lenient;
  we write a valid archive.
* It writes UTF-8 entry-name bytes with the UTF-8 general-purpose flag **clear**, which is why
  ``unzip -l`` mojibakes a Korean deck name. Python always sets the flag; keeping generated deck
  filenames ASCII sidesteps the question entirely.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import build

_FILE_SCHEME = "file://"


def media_paths(pres) -> list[Path]:
    """Every local media file the presentation references, in first-seen order.

    Mirrors how ``elements.image`` writes them: ``fill.media.url.absolute_string`` holds a
    percent-encoded ``file://`` URL. Non-``file://`` URLs are skipped — a web element points at a
    live page, not a file to pack (and nothing in the generator emits one; see ``build.py``'s
    Glossa NOTE).
    """
    seen: dict[Path, None] = {}
    for cue in pres.cues:
        for action in cue.actions:
            for wrapper in action.slide.presentation.base_slide.elements:
                if not wrapper.element.fill.HasField("media"):
                    continue
                url = wrapper.element.fill.media.url.absolute_string
                if url.startswith(_FILE_SCHEME):
                    seen[Path(unquote(urlparse(url).path))] = None
    return list(seen)


def write_bundle(pro_path: str | Path, out: str | Path | None = None) -> Path:
    """Zip ``pro_path`` and its media into a sibling ``.probundle``; return its path.

    Raises ``FileNotFoundError`` when a referenced media file is gone. A bundle silently short a
    hymn page is worse than a failed build — the operator would only find out on Sunday.
    """
    pro_path = Path(pro_path)
    out = Path(out) if out else pro_path.with_suffix(".probundle")
    files = media_paths(build.load(str(pro_path)))
    missing = [p for p in files if not p.is_file()]
    if missing:
        raise FileNotFoundError(
            f"{pro_path.name} references {len(missing)} missing media file(s): "
            + ", ".join(str(p) for p in missing[:5])
        )

    # Media keeps its absolute path — that is the join key ProPresenter rewrites URLs by on
    # import; the .pro sits at the archive root. Media first, as PP's own export writes it.
    entries = [(str(p), p) for p in files] + [(pro_path.name, pro_path)]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED, allowZip64=True) as zf:
        for name, path in entries:
            # ZipInfo built directly (not from_file) keeps the leading "/" that ZipFile.write
            # would strip. force_zip64 gives every entry the zip64 headers PP's own bundles
            # carry, rather than only entries over 4 GiB.
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_STORED
            with zf.open(info, "w", force_zip64=True) as dst:
                dst.write(path.read_bytes())
    return out
