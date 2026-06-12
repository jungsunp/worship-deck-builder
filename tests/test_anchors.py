"""Tests for worship_deck.keynote.anchors — landmark-based section-anchor detection (#98).

Runs against the sanitized per-slide text dump of a real master.key
(tests/fixtures/master_slide_texts.json); CI-safe, no Mac/Keynote needed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from worship_deck.keynote.anchors import TemplateAnchors, detect_anchors

_FIXTURE = Path(__file__).parent / "fixtures" / "master_slide_texts.json"

# The reference anchor map of the dumped master.key — the same numbers config/slide_map.yaml
# documents and build() used to hard-code.
EXPECTED = TemplateAnchors(
    worship_start=6,
    worship_len=41,
    call_ref=47,
    call_verse=48,
    call_verse_count=1,
    confession_divider=57,
    confession_lyric_count=8,
    choir_title=77,
    choir_lyric_count=17,
    offering_title=97,
    announcements_start=117,
    announcements_count=5,
    sermon_ref=127,
    sermon_verse_start=129,
    sermon_verse_count=4,
    sermon_title=134,
    special_start=135,
    special_count=18,
)


@pytest.fixture()
def slide_texts() -> list[list[str]]:
    return json.loads(_FIXTURE.read_text())


def test_detects_reference_template_map(slide_texts: list[list[str]]) -> None:
    assert detect_anchors(slide_texts) == EXPECTED


def test_inserted_slides_shift_downstream_anchors(slide_texts: list[list[str]]) -> None:
    """A replaced template with two extra static slides before 고백의 찬양 (after slide 50):
    everything earlier keeps its anchor, everything later shifts by 2 — no literals to fix."""
    shifted = slide_texts[:50] + [[], ["새 안내문"]] + slide_texts[50:]

    a = detect_anchors(shifted)

    assert (a.worship_start, a.worship_len, a.call_ref, a.call_verse) == (6, 41, 47, 48)
    assert a.confession_divider == EXPECTED.confession_divider + 2
    assert a.choir_title == EXPECTED.choir_title + 2
    assert a.offering_title == EXPECTED.offering_title + 2
    assert a.announcements_start == EXPECTED.announcements_start + 2
    assert (a.sermon_ref, a.sermon_verse_start, a.sermon_title) == (129, 131, 136)
    assert (a.special_start, a.special_count) == (137, 18)


def test_grown_sections_change_detected_counts(slide_texts: list[list[str]]) -> None:
    """Section sizes are measured, not stored: an extra announcement slide and an extra sermon
    verse slide in the template grow the detected counts (and shift later anchors)."""
    grown = (
        slide_texts[:121]
        + [["7. 새 안내", "내용"]]
        + slide_texts[121:132]
        + [slide_texts[131]]  # duplicate the last [눅 …, 개역한글] verse-body slide
        + slide_texts[132:]
    )

    a = detect_anchors(grown)

    assert (a.announcements_start, a.announcements_count) == (117, 6)
    assert (a.sermon_verse_start, a.sermon_verse_count) == (130, 5)
    assert a.sermon_title == EXPECTED.sermon_title + 2
    assert (a.special_start, a.special_count) == (137, 18)


def test_missing_landmark_fails_loud(slide_texts: list[list[str]]) -> None:
    broken = [[ln for ln in lines if ln != "성가대 찬양"] for lines in slide_texts]

    with pytest.raises(RuntimeError, match="성가대"):
        detect_anchors(broken)


def test_ambiguous_landmark_fails_loud(slide_texts: list[list[str]]) -> None:
    dup = slide_texts + [["봉 헌", "[ 다른 찬양 ]"]]

    with pytest.raises(RuntimeError, match="봉헌"):
        detect_anchors(dup)
