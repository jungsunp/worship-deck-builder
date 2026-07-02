"""Toolchain checks for the vendored ProPresenter protobuf bindings (#165)."""

import pytest

from worship_deck.propresenter import pb  # noqa: F401 -- puts pb/ on sys.path

# Bindings are generated (scripts/gen_proto.sh), not committed — skip if absent.
presentation_pb2 = pytest.importorskip(
    "presentation_pb2", reason="run scripts/gen_proto.sh to generate protobuf bindings"
)
from worship_deck.propresenter import roundtrip  # noqa: E402 -- after importorskip guard


def test_bindings_load_and_roundtrip_in_memory():
    """The committed *_pb2 bindings import and serialize/parse losslessly (CI-safe)."""
    pres = presentation_pb2.Presentation()
    pres.name = "Hello World"
    pres.uuid.string = "00000000-0000-0000-0000-000000000000"
    again = presentation_pb2.Presentation()
    again.ParseFromString(pres.SerializeToString())
    assert again.name == "Hello World"
    assert again.uuid.string == pres.uuid.string


@pytest.mark.local_only
def test_hello_world_roundtrip_from_sample(tmp_path):
    """Read a real sample .pro, swap its text, write + reparse (needs ProPresenter installed)."""
    sample = roundtrip._default_sample()
    if not sample.exists():
        pytest.skip("ProPresenter sample library not found")

    out = roundtrip.hello_world(sample, tmp_path / "Hello World.pro", text="Hello World")
    pres = presentation_pb2.Presentation()
    pres.ParseFromString(out.read_bytes())

    assert pres.name == "Hello World"
    assert len(pres.cues) == 1
    assert len(pres.cue_groups[0].cue_identifiers) == 1
    assert pres.cue_groups[0].cue_identifiers[0].string == pres.cues[0].uuid.string
    rtf = b"".join(
        e.element.text.rtf_data
        for a in pres.cues[0].actions
        if a.HasField("slide")
        for e in a.slide.presentation.base_slide.elements
        if e.element.HasField("text")
    )
    assert b"Hello World" in rtf
    assert b"Point #1" not in rtf
