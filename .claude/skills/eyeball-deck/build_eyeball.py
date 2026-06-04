#!/usr/bin/env python3
"""Build a draft deck from the template, fill one section, and open it in Keynote to review.

Used by the `eyeball-deck` skill. Produces a real .key the user can open and inspect before
shipping, instead of trusting PNG renders alone. Handles the Keynote-automation footguns that
otherwise cause -609 / timeouts (see SKILL.md): launch + settle the app, then close stale docs
before driving it.

Examples:
    python build_eyeball.py song                       # sample song into the worship section
    python build_eyeball.py song --title "주 은혜임을" --line "내 평생에 가는 길" --line "..." \
        --at 7 --existing 10
    python build_eyeball.py verse                       # sample verses into 예배의 부름 (slide 48)
    python build_eyeball.py verse --ref "시 133:1-3" --at 48 --existing 1   # real lookup (needs keys)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]  # .claude/skills/eyeball-deck/ -> repo root
sys.path.insert(0, str(REPO / "src"))  # belt-and-suspenders if not pip-installed

from worship_deck.bible.verses import Verse  # noqa: E402
from worship_deck.keynote.build import (  # noqa: E402
    fill_song_slides,
    fill_verse_slides,
    save_draft,
)
from worship_deck.lyrics.transcribe import Song  # noqa: E402

SAMPLE_SONG = Song(
    title="주 은혜임을",
    lines=[
        "내 평생에 가는 길",
        "순탄하여 늘 잔잔한 강 같든지",
        "큰 풍파로 무섭고",
        "어렵든지 나의 영혼은 늘 편하다",
    ],
)
SAMPLE_VERSES = [
    Verse(1, "형제가 연합하여 동거함이", "Behold, how good and pleasant it is"),
    Verse(2, "머리에 있는 보배로운 기름이", "It is like the precious oil on the head"),
    Verse(3, "헐몬의 이슬이 시온의 산들에", "It is like the dew of Hermon"),
]


def _keynote_doc_count() -> int | None:
    """Number of open Keynote documents, or None if the query failed."""
    r = subprocess.run(
        ["osascript", "-e", 'tell application "Keynote" to count documents'],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return None
    try:
        return int(r.stdout.strip())
    except ValueError:
        return None


def ensure_keynote_ready(settle: int = 8, tries: int = 20) -> None:
    """Launch Keynote, wait for scripting, and confirm it has ZERO open documents.

    Documents left open by a prior aborted run *stack up* and wedge Keynote — the next open/save
    then hangs until the timeout (this is what caused a long retry spiral). So we don't just fire
    a close-all and hope: we close, then poll the document count to 0, retrying, and bail loudly
    if it won't clear.

    NEVER force-quit Keynote to "reset" it — that leaves the scripting bridge in a -609
    ("connection is invalid") state. A clean launch + settle, then this doc-clearing, is the
    reliable reset; if it can't clear, relaunch Keynote by hand.
    """
    subprocess.run(["open", "-a", "Keynote"], check=False)
    time.sleep(settle)
    for _ in range(tries):
        if subprocess.run(
            ["osascript", "-e", 'tell application "Keynote" to get name'],
            capture_output=True,
            text=True,
        ).returncode == 0:
            break
        time.sleep(1)
    else:
        sys.exit("Keynote did not become responsive — launch it manually, then retry.")
    # Close stale docs and CONFIRM none remain; a single leftover open doc wedges the next save.
    for _ in range(tries):
        subprocess.run(
            ["osascript", "-e", 'tell application "Keynote" to close every document saving no'],
            check=False,
        )
        if _keynote_doc_count() == 0:
            return
        time.sleep(1)
    sys.exit(
        "Keynote still has documents open after repeated close attempts — it is likely wedged "
        "(a stuck save or a modal dialog). Quit Keynote manually (do not force-quit while a save "
        "is running), relaunch, and retry."
    )


def resolve_template(arg: str | None) -> str:
    path = arg or os.environ.get("TEMPLATE_KEY") or str(REPO / "templates" / "master.key")
    path = str(Path(path).expanduser())
    if not Path(path).exists():
        sys.exit(f"Template not found: {path} (set TEMPLATE_KEY or pass --template).")
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="section", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--template", help="path to master .key (default: TEMPLATE_KEY env)")
    common.add_argument(
        "--out",
        default="/tmp/draft-eyeball.key",
        help="output draft path (default: /tmp/draft-eyeball.key — outside the project dir, so "
        "the 30MB save dodges editor/file-watcher slowdown and beats the 120s osascript timeout; "
        "pass e.g. data/drafts/draft-eyeball.key to keep it)",
    )
    common.add_argument(
        "--existing", type=int, default=1, help="template slide count for the section block"
    )
    common.add_argument("--no-open", action="store_true", help="build only; don't open Keynote")

    sp = sub.add_parser("song", parents=[common], help="fill a worship-song title + lyric slides")
    sp.add_argument("--at", type=int, default=7, help="title-slide index (default: 7)")
    sp.add_argument("--title", help="song title (default: sample)")
    sp.add_argument("--line", action="append", dest="lines", help="a lyric line; repeatable")

    vp = sub.add_parser("verse", parents=[common], help="fill a Bible-verse slide block")
    vp.add_argument("--at", type=int, default=48, help="verse-slide index (default: 48)")
    vp.add_argument("--ref", help="Korean ref for a real lookup, e.g. '시 133:1-3' (needs keys)")

    args = ap.parse_args()
    template = resolve_template(args.template)
    out = str((REPO / args.out) if not Path(args.out).is_absolute() else Path(args.out))
    Path(out).parent.mkdir(parents=True, exist_ok=True)

    ensure_keynote_ready()
    print(f"Building {out} from {Path(template).name} …", flush=True)
    save_draft(template, out)

    if args.section == "song":
        song = Song(
            title=args.title or SAMPLE_SONG.title,
            lines=args.lines or list(SAMPLE_SONG.lines),
        )
        n = fill_song_slides(out, args.at, song, existing_lyric_count=args.existing)
        first, last = args.at, args.at + n - 1
        print(f"Filled song: {n} slides ({first} title + {n - 1} lyric).")
    else:
        if args.ref:
            from worship_deck.bible.verses import lookup_verses, verse_labels

            verses = lookup_verses(args.ref)
            kr_label, en_label = verse_labels(args.ref)
        else:
            verses = SAMPLE_VERSES
            kr_label, en_label = "[시 133:1-3, 개역한글]", "[Psalms 133:1-3, ESV]"
        n = fill_verse_slides(
            out, args.at, kr_label, en_label, verses, existing_count=args.existing
        )
        first, last = args.at, args.at + n - 1
        print(f"Filled verses: {n} slides.")

    print(f"Review slides {first}–{last + 1} (the +1 confirms the next section has no leftover).")
    if not args.no_open:
        subprocess.run(["open", out], check=False)
        print(f"Opened {out} in Keynote.")


if __name__ == "__main__":
    main()
