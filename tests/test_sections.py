"""Section suggestion from canonical lyric structure (#206) — lyrics/sections.py.

Streams mirror the shapes validated against the 2026-07-12 sheets' red marks:
verse/chorus alternation (임재), a bridge (주의 나라가 임할 때), and a doubled
first verse with a short tag (성령이 오셨네).
"""

from worship_deck.lyrics import sections

V1 = ["하늘의 문을 여소서", "임재의 빛을 비추소서", "주님을 바라봅니다", "그 영광을 봅니다"]
V2 = ["주의 보좌 앞에 나아가", "은혜의 강가에 서서", "생명의 물을 마시네", "주만 바라봅니다"]
CHORUS = ["이곳에 오셔서 다스리소서", "주의 보좌로 삼으소서", "찬양 가운데 임하소서"]
BRIDGE = ["주의 나라가 임할 때", "모든 무릎 꿇겠네"]
TAG = ["성령이 오셨네", "우리 안에 오셨네"]


def test_verse_chorus_alternation_dedups_and_prefills_arrangement():
    stream = V1 + CHORUS + V1 + CHORUS + CHORUS
    secs, arrangement = sections.suggest(stream)
    assert secs == [{"label": "V1", "lines": V1}, {"label": "C", "lines": CHORUS}]
    assert arrangement == "V1 C V1 C C"


def test_repeated_block_after_chorus_is_bridge():
    stream = V1 + CHORUS + V2 + CHORUS + BRIDGE + CHORUS + BRIDGE
    secs, arrangement = sections.suggest(stream)
    assert [s["label"] for s in secs] == ["V1", "C", "V2", "B"]
    assert secs[3]["lines"] == BRIDGE
    assert arrangement == "V1 C V2 C B C B"


def test_doubled_verse_and_short_trailing_tag():
    stream = V1 + V1 + CHORUS + CHORUS + V2 + CHORUS + CHORUS + TAG
    secs, arrangement = sections.suggest(stream)
    # V1 repeats but first appears before the chorus, so it stays a verse
    assert [s["label"] for s in secs] == ["V1", "C", "V2", "TAG"]
    assert arrangement == "V1 V1 C C V2 C C TAG"


def test_no_repetition_returns_none():
    assert sections.suggest(V1 + CHORUS + V2) is None


def test_repeated_one_line_card_suppresses_suggestion():
    # a 1-line block repeating outside any section (intro/outro echo line) signals
    # fragmentation, not structure — the 8-week eval showed such suggestions are wrong
    r = ["오 주님 나를 이끄소서"]
    stream = r + V1 + CHORUS + V1 + r
    assert sections.suggest(stream) is None


def test_shared_refrain_resolves_by_tie_break():
    # verse and chorus both end with the same refrain line (말씀하시면). The refrain
    # stays inside both cards (1-line blocks never split others), and the count tie
    # between verse and chorus breaks toward the non-opening block — the chorus.
    r = ["오 주님 나를 이끄소서"]
    stream = V1 + r + V1 + r + BRIDGE + V1 + r + BRIDGE + BRIDGE + r
    secs, arrangement = sections.suggest(stream)
    assert secs == [
        {"label": "V1", "lines": V1 + r},
        {"label": "C", "lines": BRIDGE},
        {"label": "TAG", "lines": r},
    ]
    assert arrangement == "V1 V1 C V1 C C TAG"


def test_lone_trailing_echo_is_tag():
    # the song ends by singing the chorus's last line once more (하나님 아버지의 마음):
    # a single-occurrence 1-line final block is a trusted TAG, not fragmentation
    stream = V1 + CHORUS + V1 + CHORUS + CHORUS + CHORUS[-1:]
    secs, arrangement = sections.suggest(stream)
    assert secs == [
        {"label": "V1", "lines": V1},
        {"label": "C", "lines": CHORUS},
        {"label": "TAG", "lines": CHORUS[-1:]},
    ]
    assert arrangement == "V1 C V1 C C TAG"


def test_whole_song_repeated_is_a_verse_not_chorus():
    # e.g. a short call-to-worship printed once per key (입례) — one card, played N times
    secs, arrangement = sections.suggest(V1 + V1 + V1)
    assert secs == [{"label": "V1", "lines": V1}]
    assert arrangement == "V1 V1 V1"


def test_single_repeated_line_is_not_a_block():
    # a lone line repeating (< 2-line span) is no evidence of section structure
    stream = V1 + ["후렴 한 줄"] + V2 + ["후렴 한 줄"]
    assert sections.suggest(stream) is None


def test_stanza_breaks_are_authored_boundaries():
    # blank lines switch to stanza mode: stanzas are the blocks, and a stanza made of
    # already-seen blocks (V1 + C + C here) is peeled into them
    stream = V1 + [""] + CHORUS + ["", ""] + V1 + CHORUS + CHORUS
    secs, arrangement = sections.suggest(stream)
    assert secs == [{"label": "V1", "lines": V1}, {"label": "C", "lines": CHORUS}]
    assert arrangement == "V1 C V1 C C"


def test_stanza_mode_keeps_shared_refrain_and_peels_trailing_tag():
    # the 말씀하시면 (7/19) shape: verse and final chorus stanza share a closing refrain
    # line. Stanza boundaries keep the refrain inside the verse card (tiling mode
    # fragments it into a 1-line card and suppresses); the final "chorus + refrain"
    # stanza peels into a C occurrence + a TAG card.
    refrain = ["오 주님 나를 이끄소서"]
    verse = ["주님 말씀하시면 내가 나아가리다", "나의 가고 서는 것 주님 뜻에 있으니"] + refrain
    chorus = ["뜻하신 그 곳에 나 있기 원합니다", "연약한 내 영혼 통하여 일하소서", "주님 나라와 그 뜻을 위하여"]
    stanza = [""]
    stream = (
        verse + stanza + verse + stanza + chorus + stanza + verse + stanza
        + chorus + stanza + chorus + refrain
    )
    secs, arrangement = sections.suggest(stream)
    assert secs == [
        {"label": "V1", "lines": verse},
        {"label": "C", "lines": chorus},
        {"label": "TAG", "lines": refrain},
    ]
    assert arrangement == "V1 V1 C V1 C C TAG"


def test_stanza_mode_without_repetition_returns_none():
    # hymn-style pages: distinct stanzas per verse, nothing repeats — no labels to infer
    stream = V1 + [""] + CHORUS + [""] + V2
    assert sections.suggest(stream) is None


def test_flatten_is_the_blank_line_mirror():
    secs, _ = sections.suggest(V1 + CHORUS + V1 + CHORUS + CHORUS)
    assert sections.flatten(secs) == V1 + [""] + CHORUS
