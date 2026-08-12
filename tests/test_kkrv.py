"""Tests for worship_deck.bible.kkrv — 개역한글 lookup from bundled KRV dataset.

All tests are CI-safe: they read from the committed data file; no API key needed.
"""

from __future__ import annotations

import pytest

from worship_deck.bible.kkrv import fetch_korean
from worship_deck.bible.ref import BibleRef, parse_ref

# ---------------------------------------------------------------------------
# Happy-path — content checks
# ---------------------------------------------------------------------------

def test_single_verse() -> None:
    ref = parse_ref("창 1:1")
    text = fetch_korean(ref)
    assert "태초에" in text


def test_verse_range() -> None:
    ref = parse_ref("눅 22:14-24")
    lines = fetch_korean(ref).splitlines()
    assert len(lines) == 11
    assert "유월절" in "\n".join(lines)  # appears in verse 15


def test_chapter_only() -> None:
    ref = parse_ref("시 133")
    lines = fetch_korean(ref).splitlines()
    assert len(lines) == 3   # Psalm 133 has 3 verses


def test_numbered_book_roman_numeral_fix() -> None:
    # 고전 = 1 Corinthians; KorRV.json stores this as "I Corinthians"
    ref = parse_ref("고전 13:1")
    text = fetch_korean(ref)
    assert text  # non-empty — proves the name-fix mapping works


def test_revelation_name_fix() -> None:
    # KorRV.json stores as "Revelation of John"; BibleRef uses "Revelation"
    ref = parse_ref("계 22:21")
    text = fetch_korean(ref)
    assert text


# ---------------------------------------------------------------------------
# 세례 vs 침례 — the bundled text must read 세례 (Presbyterian usage)
# ---------------------------------------------------------------------------

def test_baptism_reads_serye_not_chimrye() -> None:
    """scrollmapper's KorRV dump was a Baptist redaction that wrote 침례 for 세례.

    The dataset now comes from bolls.life (scripts/fetch_krv.py); guard against a
    re-import of the bad text.
    """
    text = fetch_korean(parse_ref("요 1:33"))
    assert "세례" in text
    assert "침례" not in text


def test_no_chimrye_anywhere_in_dataset() -> None:
    from worship_deck.bible.kkrv import _DATA_PATH

    # count, not `in`, so a failure doesn't dump the whole 8 MB file into the report
    assert _DATA_PATH.read_text(encoding="utf-8").count("침례") == 0


def test_original_1961_orthography_preserved() -> None:
    """The church's master.key renders 시 147:7 with the original 찌 spelling.

    The old dataset had modernised these to 지, silently diverging from the deck.
    """
    assert fetch_korean(parse_ref("시 147:7")).endswith("찬양할찌어다")


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------

def test_unknown_book_raises() -> None:
    ref = BibleRef("NotABook", 1, 1, None)
    with pytest.raises(ValueError, match="Book not found"):
        fetch_korean(ref)


def test_unknown_chapter_raises() -> None:
    ref = BibleRef("Genesis", 999, 1, None)
    with pytest.raises(ValueError, match="Chapter not found"):
        fetch_korean(ref)


def test_unknown_verse_raises() -> None:
    ref = BibleRef("Genesis", 1, 999, None)
    with pytest.raises(ValueError, match="Verse not found"):
        fetch_korean(ref)
