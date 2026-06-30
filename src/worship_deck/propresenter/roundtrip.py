"""Hello-world ``.pro`` round-trip — proof that the protobuf toolchain can read
and write ProPresenter documents (issue #165, the v3 .key→.pro migration).

This is intentionally minimal: it loads an existing (known-valid) ``.pro``,
reduces it to its single title slide, swaps the visible text, and writes a new
``.pro``. It is NOT the deck generator — ground-up serialization from
``ServiceData`` is the later #172 work. Its only job is to prove the loop
read → mutate → write → ProPresenter renders it.

Run as a script to drop a file into a ProPresenter library, then open it:

    python -m worship_deck.propresenter.roundtrip --out "<library>/Hello World.pro"
"""

from __future__ import annotations

import uuid as _uuid
from pathlib import Path

from . import pb  # noqa: F401 -- side effect: puts pb/ on sys.path for the bare *_pb2 imports

import cue_pb2
import presentation_pb2

_SAMPLE_TEXT = b"Point #1"  # the visible run on the sample deck's first slide


def _has_sample_text(action) -> bool:
    if not action.HasField("slide"):
        return False
    return any(
        e.element.HasField("text") and _SAMPLE_TEXT in e.element.text.rtf_data
        for e in action.slide.presentation.base_slide.elements
    )


def hello_world(sample_pro: str | Path, out_pro: str | Path, text: str = "Hello World") -> Path:
    """Read ``sample_pro``, swap its title text to ``text``, write ``out_pro``."""
    pres = presentation_pb2.Presentation()
    pres.ParseFromString(Path(sample_pro).read_bytes())

    # Fresh identity so ProPresenter imports it as a new document, not a dup.
    pres.name = text
    pres.uuid.string = str(_uuid.uuid4()).upper()

    title_cue = next(c for c in pres.cues if any(_has_sample_text(a) for a in c.actions))
    for action in title_cue.actions:
        if not action.HasField("slide"):
            continue
        for e in action.slide.presentation.base_slide.elements:
            el = e.element
            if el.HasField("text") and _SAMPLE_TEXT in el.text.rtf_data:
                el.text.rtf_data = el.text.rtf_data.replace(_SAMPLE_TEXT, text.encode("utf-8"))

    # Collapse to just the title slide.
    keep = cue_pb2.Cue()
    keep.CopyFrom(title_cue)
    del pres.cues[:]
    pres.cues.append(keep)
    group = pres.cue_groups[0]
    del pres.cue_groups[1:]
    del group.cue_identifiers[:]
    group.cue_identifiers.add().string = keep.uuid.string

    out = Path(out_pro)
    out.write_bytes(pres.SerializeToString())
    return out


def _default_sample() -> Path:
    return (
        Path.home()
        / "Library/Application Support/RenewedVision/ProPresenter"
        / "UserWorkspaces/ProPresenter/Libraries/Sample 1/Sample Presentation.pro"
    )


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Write a hello-world ProPresenter .pro")
    ap.add_argument("--sample", type=Path, default=_default_sample(), help="source .pro to read")
    ap.add_argument("--out", type=Path, required=True, help="destination .pro to write")
    ap.add_argument("--text", default="Hello World", help="title text to set")
    args = ap.parse_args()

    written = hello_world(args.sample, args.out, args.text)
    print(f"Wrote {written}")
    print("Open it in ProPresenter (restart PP if the library doesn't refresh) and confirm it renders.")
