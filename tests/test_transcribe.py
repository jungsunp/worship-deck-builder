"""Tests for worship_deck.lyrics.transcribe — title detection, gasazip lookup, misses."""

from __future__ import annotations

import pytest

from worship_deck.lyrics import transcribe as T
from worship_deck.lyrics.transcribe import Song, transcribe


# ---------------------------------------------------------------------------
# _filter_lyric_fragments — pure, no I/O
# ---------------------------------------------------------------------------

def test_filter_keeps_hangul_drops_chords_numbers_english_urls() -> None:
    raw = [
        "G", "D/F#", "Bm7",                       # chords
        "26", "1.", "= 66",                       # measure numbers / tempo
        "Isaiah 61&One", "https://blog.naver.com/jskyscore",  # english / watermark
        "내 주를 가까이",                          # lyric
        "주님을 가 까 이 함 이",                    # fragmented lyric
    ]
    assert T._filter_lyric_fragments(raw) == ["내 주를 가까이", "주님을 가 까 이 함 이"]


def test_filter_drops_known_hangul_noise() -> None:
    raw = ["도돌이표는 항상 포함입니다", "아이자야씩스티원", "나는 예배하네"]
    assert T._filter_lyric_fragments(raw) == ["나는 예배하네"]


# ---------------------------------------------------------------------------
# _detect_titles — tallest Hangul lines near the top, tallest first, edges trimmed
# ---------------------------------------------------------------------------

def test_detect_titles_real_sheet_shape() -> None:
    # Shape of the real 보좌 앞으로 sheet: a taller handwritten mark with no Hangul,
    # the title with a merged red "•all" mark, then watermark/credits and lyrics.
    # The short lyric line also qualifies — as a lower-priority candidate (#202).
    lines = [
        (0.0634, 'vx3(aim) - VX3 (ky change "F")'),
        (0.0474, "•all 보좌 앞으로"),
        (0.0269, "blog.naver.com/x 주님의 보혈 의지하는 Words & Music by 민호기"),
        (0.0318, "E B/D# C#m G#m/B"),
        (0.0444, "V 주님의 보혈 . 의지하 는맘 .으로"),
    ]
    assert T._detect_titles(lines) == ["보좌 앞으로", "주님의 보혈 . 의지하 는맘 .으로"]


def test_detect_titles_skips_noise_and_handles_empty() -> None:
    assert T._detect_titles([]) == []
    assert T._detect_titles([(0.05, "VX3 chords only")]) == []
    # Known Hangul noise (watermark phonetics) never becomes a title candidate.
    assert T._detect_titles([(0.09, "아이자야씩스티원"), (0.04, "나는 예배하네")]) == ["나는 예배하네"]


def test_detect_titles_ignores_credit_on_the_title_baseline() -> None:
    # 2026-07-26 sheet 2: Vision merges the credit into the title's line, and the English
    # drags the Hangul ratio to 0.46 — under the bar, so the whole song used to be lost.
    lines = [(0.05, "하나님 아버지의 마음 Words & Music by 설경육")]
    assert T._detect_titles(lines) == ["하나님 아버지의 마음"]
    assert T._detect_titles([(0.05, "부흥 작사 고형원")]) == ["부흥"]


def test_detect_titles_ignores_taller_handwritten_marks() -> None:
    # Real sheet-2 shape: handwriting with some Hangul ("드럼만") out-talls the
    # printed title but is mostly latin/digits — the ratio filter rejects it.
    lines = [
        (0.0380, "181-8182--82-Cnter.-v3-74-6x4 all"),
        (0.0526, "드럼만 - ((83)"),
        (0.0300, "죄에서 자유를 얻게 함은"),
        (0.0237, "Hymn 268 • 천천히 L.E.Jones, 1889"),
    ]
    assert T._detect_titles(lines) == ["죄에서 자유를 얻게 함은"]


def test_detect_titles_rejects_lyric_lines_on_continuation_pages() -> None:
    # Continuation pages have no printed title; their tallest Hangul is a note-split
    # lyric line, which the Hangul length cap rejects → [] → no online lookup.
    lines = [
        (0.0919, 'CX3-B-CXX-C (주의 보혈")'),
        (0.0486, "포- 대를 향하여- 그리- 스도 예수안-에서- 부름 의상을-위하-여 달려가 - 노라-"),
    ]
    assert T._detect_titles(lines) == []


# ---------------------------------------------------------------------------
# transcribe — orchestration with all stages mocked
# ---------------------------------------------------------------------------

_OCR_LINES = [
    (0.05, "내 주를 가까이"),  # tallest Hangul line → title
    (0.02, "G"),
    (0.03, "내 주 를"),
    (0.03, "가까이"),
    (0.02, "https://x"),
]


def test_transcribe_uses_online_match_when_confident(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from worship_deck.lyrics import online

    monkeypatch.setattr(T, "_vision_ocr", lambda p: _OCR_LINES)
    seen: dict = {}

    def fake_lookup(queries: list[str], fragments: list[str]) -> tuple:
        seen["queries"], seen["fragments"] = queries, fragments
        return online.Candidate(
            song_id="1", title="내 주를 가까이", artist="x", lines=["내 주를 가까이 하게 함은"]
        ), []

    monkeypatch.setattr(online, "lookup", fake_lookup)
    songs = transcribe("whatever.png")

    assert songs == [
        Song(
            title="내 주를 가까이",
            lines=["내 주를 가까이 하게 함은"],
            provenance={  # gasazip origin surfaced by the review badge (#200)
                "source": "gasazip", "song_id": "1", "artist": "x",
                "cand_cov": 0.0, "ocr_cov": 0.0,
            },
            fragments=seen["fragments"],  # kept for review re-search (#203)
        )
    ]
    # The tallest line leads; the shorter tall lines follow as further candidates (#202).
    assert seen["queries"][0] == "내 주를 가까이"
    # Lookup ranks against the filtered Hangul fragments only.
    assert "https://x" not in seen["fragments"] and "G" not in seen["fragments"]


def test_transcribe_queries_every_title_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2026-07-12 sheet 003 shape (#202): the tallest Hangul line is garbled
    handwriting, so the printed title below it must also reach the lookup."""
    from worship_deck.lyrics import online

    ocr = [
        (0.09, "그런가 보시면 탄생"),  # garbled handwriting, tallest
        (0.03, "허무한 시절 지날때"),  # printed title
    ]
    monkeypatch.setattr(T, "_vision_ocr", lambda p: ocr)
    seen: dict = {}

    def fake_lookup(queries: list[str], fragments: list[str]) -> tuple:
        seen["queries"] = queries
        return online.Candidate(
            song_id="602",
            title="성령이 오셨네",
            artist="심형진",
            lines=["성령이 오셨네 내 맘에 오셨네"],
        ), []

    monkeypatch.setattr(online, "lookup", fake_lookup)
    (song,) = transcribe("whatever.png")
    assert seen["queries"] == ["그런가 보시면 탄생", "허무한 시절 지날때"]
    assert song.title == "성령이 오셨네"


def test_transcribe_rebreaks_overlong_online_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An over-long gasazip line is re-broken to fit the lyric banner (#126)."""
    from worship_deck.lyrics import online

    monkeypatch.setattr(T, "_vision_ocr", lambda p: _OCR_LINES)
    long_line = "이전에 있는 것은 모두 잊어버리고 앞에 계신 그리스도께로 달려가 노라"
    monkeypatch.setattr(
        online,
        "lookup",
        lambda *a, **kw: (
            online.Candidate(song_id="1", title="내 주를 가까이", artist="x", lines=[long_line]),
            [],
        ),
    )
    (song,) = transcribe("whatever.png")

    assert len(song.lines) > 1  # split, not passed through
    assert " ".join(song.lines) == long_line  # text preserved


def test_transcribe_miss_returns_empty_song_with_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No confident match (#213): no lyrics, but the scored candidates ride along so
    review can offer the picker without another throttled search."""
    from worship_deck.lyrics import online

    monkeypatch.setattr(T, "_vision_ocr", lambda p: _OCR_LINES)
    scored = [
        online.Candidate(song_id="9", title="다른 곡", artist="y", lines=["가사 한 줄", ""],
                         cand_cov=0.2, ocr_cov=0.1)
    ]
    monkeypatch.setattr(online, "lookup", lambda *a, **kw: (None, scored))
    (song,) = transcribe("whatever.png")

    assert song.title == "내 주를 가까이"  # the detected title, for the operator to correct
    assert song.lines == [] and song.sections == []  # note-split OCR never becomes slide text
    assert song.provenance["source"] == "ocr"
    assert song.provenance["titles"][0] == "내 주를 가까이"  # chips for correcting a misread
    assert song.candidates == [
        {"song_id": "9", "title": "다른 곡", "artist": "y",
         "cand_cov": 0.2, "ocr_cov": 0.1, "preview": ["가사 한 줄"]}
    ]
    assert song.fragments  # kept for review re-search scoring (#203)


def test_transcribe_detects_continuation_by_lyric_overlap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2026-07-26 sheet 3: a continuation page whose *misread* title looks like a real one.
    Its lyrics are already inside the previous song, which is the actual signal (#213) —
    and knowing that up front skips the doomed lookup entirely."""
    from worship_deck.lyrics import online

    prev = ["말씀 앞에서 경외함으로", "주께 홀로 섭니다", "생명의 말씀 읽고 순종해"]
    monkeypatch.setattr(T, "_vision_ocr", lambda p: [(0.05, "말씀 앞에서 경외함으로 주께 홀로 섭니다")])
    monkeypatch.setattr(online, "lookup", lambda *a, **kw: pytest.fail("should not look up"))
    (song,) = transcribe("whatever.png", previous_lines=prev)

    assert song.provenance == {"source": "ocr", "continuation": True}
    assert song.title == "" and song.fragments


def test_transcribe_titleless_separate_song_is_not_folded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2026-07-26 sheet 1: no title survived detection, but the lyrics are nothing like the
    previous song's — a separate song, so it keeps its own card instead of being folded
    into (and lost inside) the one before it."""
    from worship_deck.lyrics import online

    prev = ["주님 말씀하시면 내가 나아가리다", "주님 뜻이 아니면 내가 멈춰서리다"]
    lyric = "이 세상 그 어떤 것도 주님의 사랑에서 나를 끊을 수 없네"
    monkeypatch.setattr(T, "_vision_ocr", lambda p: [(0.03, lyric)])
    monkeypatch.setattr(online, "lookup", lambda *a, **kw: pytest.fail("no title to search"))
    (song,) = transcribe("whatever.png", previous_lines=prev)

    assert "continuation" not in song.provenance
    assert song.title == "" and song.lines == [] and song.fragments == [lyric]


# ---------------------------------------------------------------------------
# chunk — pure grouping into <= max_lines slides
# ---------------------------------------------------------------------------

def test_chunk_empty_and_all_blank() -> None:
    assert T.chunk([]) == []
    assert T.chunk(["", "   ", "\t"]) == []


def test_chunk_single_line() -> None:
    assert T.chunk(["나는 예배하네"]) == [["나는 예배하네"]]


def test_chunk_exactly_max_lines_is_one_slide() -> None:
    assert T.chunk(["a", "b"]) == [["a", "b"]]


def test_chunk_groups_by_count_default_two() -> None:
    assert T.chunk(["a", "b", "c"]) == [["a", "b"], ["c"]]


def test_chunk_blank_line_forces_break() -> None:
    assert T.chunk(["a", "", "b"]) == [["a"], ["b"]]


def test_chunk_stanza_longer_than_max_splits_within_stanza() -> None:
    # A 3-line stanza still splits by count; the blank only ends the prior stanza.
    assert T.chunk(["a", "b", "c", "", "d"]) == [["a", "b"], ["c"], ["d"]]


def test_chunk_collapses_leading_trailing_and_repeated_blanks() -> None:
    assert T.chunk(["", "", "a", "b", "", "", "c", "", ""]) == [["a", "b"], ["c"]]


def test_chunk_whitespace_only_line_is_a_break() -> None:
    assert T.chunk(["a", "   ", "b"]) == [["a"], ["b"]]


def test_chunk_custom_max_lines() -> None:
    assert T.chunk(["a", "b", "c", "d"], max_lines=3) == [["a", "b", "c"], ["d"]]


# ---------------------------------------------------------------------------
# parse_arrangement / arranged_chunks — labeled-section play-order fan-out (#113)
# ---------------------------------------------------------------------------

def test_parse_arrangement_splits_into_labels() -> None:
    # No ×N counter: a label per played group; repeats are explicit repetition.
    assert T.parse_arrangement("V1 C V1 C B C") == ["V1", "C", "V1", "C", "B", "C"]


def test_parse_arrangement_dash_form() -> None:
    assert T.parse_arrangement("V1-C-C") == ["V1", "C", "C"]


def test_parse_arrangement_tolerates_junk_and_empty() -> None:
    assert T.parse_arrangement("") == []
    assert T.parse_arrangement("   ") == []
    assert T.parse_arrangement("  V1   C  ") == ["V1", "C"]


def test_arranged_chunks_no_sections_equals_chunk() -> None:
    # No labeled sections (choir/confession/legacy worship) -> chunk(song.lines), empty labels.
    lines = ["a", "b", "c", "", "d", "", "e", "f"]
    song = Song(title="t", lines=lines)
    assert T.arranged_chunks(song) == [("", c) for c in T.chunk(lines)]


def test_arranged_chunks_empty_arrangement_plays_sections_in_order() -> None:
    song = Song(
        title="t",
        sections=[
            {"label": "V1", "lines": ["v1a", "v1b"]},
            {"label": "C", "lines": ["ca", "cb"]},
        ],
    )
    assert T.arranged_chunks(song) == [("V1", ["v1a", "v1b"]), ("C", ["ca", "cb"])]


def test_arranged_chunks_interleaved_repeats_ppdae() -> None:
    # 푯대 shape: V1/C/V2/B sections; play V1 C V2 C C B C C C (repeats by repeated labels).
    song = Song(
        title="푯대를 향하여",
        sections=[
            {"label": "V1", "lines": ["v1a", "v1b"]},
            {"label": "C", "lines": ["후렴a", "후렴b"]},
            {"label": "V2", "lines": ["v2a", "v2b"]},
            {"label": "B", "lines": ["브릿지"]},
        ],
        arrangement="V1 C V2 C C B C C C",
    )
    chunks = T.arranged_chunks(song)
    chorus = [("C", ["후렴a", "후렴b"])]
    assert chunks == (
        [("V1", ["v1a", "v1b"])] + chorus + [("V2", ["v2a", "v2b"])] + chorus * 2
        + [("B", ["브릿지"])] + chorus * 3
    )


def test_arranged_chunks_whole_song_repeated() -> None:
    # 보좌 shape: one 2-line section played 6x via 6 repeated labels -> 6 slides.
    song = Song(
        title="보좌 앞으로",
        sections=[{"label": "V1", "lines": ["주님의 보혈", "의지하는 맘으로"]}],
        arrangement="V1 V1 V1 V1 V1 V1",
    )
    assert T.arranged_chunks(song) == [("V1", ["주님의 보혈", "의지하는 맘으로"])] * 6


def test_arranged_chunks_skips_unknown_label() -> None:
    # A label with no matching section (operator typo / deleted card) is skipped, not crashed.
    song = Song(
        title="t",
        sections=[{"label": "V1", "lines": ["a"]}, {"label": "C", "lines": ["b"]}],
        arrangement="V1 PC C",
    )
    assert T.arranged_chunks(song) == [("V1", ["a"]), ("C", ["b"])]


# ---------------------------------------------------------------------------
# detect_arrangement_hint — printed arrangement string near the top (#113)
# ---------------------------------------------------------------------------

def test_detect_arrangement_hint_dash_form() -> None:
    lines = [(0.06, "V-C-V-Cx2-B-Cx3"), (0.03, "내게 유익하던 것을")]
    assert T.detect_arrangement_hint(lines) == "V-C-V-Cx2-B-Cx3"


def test_detect_arrangement_hint_space_form_with_verse_numbers() -> None:
    lines = [(0.06, "V1 V2 PC C V1 PC×2 Cx3 V5")]
    assert T.detect_arrangement_hint(lines) == "V1 V2 PC C V1 PC×2 Cx3 V5"


def test_detect_arrangement_hint_rejects_chords_and_lyrics() -> None:
    assert T.detect_arrangement_hint([(0.05, "A C#m7 D E")]) == ""
    assert T.detect_arrangement_hint([(0.05, "Am C G")]) == ""
    assert T.detect_arrangement_hint([(0.05, "내 주를 가까이")]) == ""
    assert T.detect_arrangement_hint([]) == ""
    assert T.detect_arrangement_hint([(0.05, "V C")]) == ""  # too few tokens


def test_transcribe_attaches_arrangement_hint_online(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from worship_deck.lyrics import online

    ocr = [(0.06, "V-C-V-Cx2-B-Cx3")] + _OCR_LINES
    monkeypatch.setattr(T, "_vision_ocr", lambda p: ocr)
    monkeypatch.setattr(
        online,
        "lookup",
        lambda *a, **kw: (
            online.Candidate(
                song_id="1", title="내 주를 가까이", artist="x", lines=["내 주를 가까이 하게 함은"]
            ),
            [],
        ),
    )
    (song,) = transcribe("whatever.png")
    assert song.arrangement_hint == "V-C-V-Cx2-B-Cx3"
    assert song.arrangement == ""  # hint is never auto-applied
