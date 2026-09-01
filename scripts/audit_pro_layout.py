"""Report every text box in a generated ``.pro`` whose text does not fit inside it.

ProPresenter does not reflow an overfull text box — it flags the slide ("one or more text
boxes are too small") and clips whatever runs past the bottom, which on a Sunday morning means
a verse the congregation simply cannot read. The generator therefore sizes its own type at
authoring time (``styles._fit_scale``), but that is an estimate; this is the check on it.

``measure_text.swift`` lays each element's RTF out through AppKit + CoreText — the same path
ProPresenter uses — so a clean run here means the deck really fits. Run it after any change to
the type scale or the frame insets in ``propresenter/styles.py``:

    python scripts/audit_pro_layout.py /path/to/deck.pro

Audit a file the generator just wrote, not one sitting in a ProPresenter library: PP rewrites
the decks it opens (reordering cues, adding empty RTF to shape elements), so a library copy is
no longer the bytes under test. macOS only — it needs the church's fonts and CoreText.
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path

from worship_deck.propresenter import build

MEASURE = Path(__file__).with_name("measure_text.swift")


def measure(items: list[tuple[bytes, float]]) -> list[float]:
    """The laid-out height of each ``(rtf, box width)``, via CoreText."""
    if not items:
        return []
    payload = [{"rtf": base64.b64encode(rtf).decode(), "width": w} for rtf, w in items]
    try:
        proc = subprocess.run(
            ["swift", str(MEASURE)],
            input=json.dumps(payload).encode(),
            capture_output=True,
            check=True,
        )
    except FileNotFoundError:
        raise SystemExit("`swift` not found — install the Xcode Command Line Tools") from None
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"measure_text.swift failed:\n{e.stderr.decode()}") from None
    return json.loads(proc.stdout)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pro", help="the .pro file to audit")
    ap.add_argument("--all", action="store_true", help="also list the boxes that do fit")
    args = ap.parse_args()

    pres = build.load(args.pro)
    by_uuid = {cue.uuid.string: cue for cue in pres.cues}

    rows: list[tuple[int, str, str, float]] = []
    items: list[tuple[bytes, float]] = []
    number = 0
    for group in pres.cue_groups:
        for ident in group.cue_identifiers:
            number += 1
            cue = by_uuid[ident.string]
            for element in cue.actions[0].slide.presentation.base_slide.elements:
                graphic = element.element
                if not graphic.text.rtf_data:
                    continue
                rows.append((number, group.group.name, cue.name, graphic.bounds.size.height))
                items.append((graphic.text.rtf_data, graphic.bounds.size.width))

    overflowing = 0
    for (number, group_name, cue_name, box_h), needed in zip(rows, measure(items)):
        over = needed - box_h
        if over > 0:
            overflowing += 1
        if over > 0 or args.all:
            mark = "OVER" if over > 0 else "ok  "
            print(f"{mark} slide {number:3d} ({group_name}/{cue_name})  "
                  f"needs {needed:6.0f} in {box_h:5.0f}  ({over:+.0f})")

    print(f"\n{overflowing} overflowing text box(es) of {len(rows)}")
    return 1 if overflowing else 0


if __name__ == "__main__":
    sys.exit(main())
