"""Tests for worship_deck.announce_suggest — /prep-week's 교회소식 spec → review sidecar (#209).

CI-safe: CoreText is faked (``_measure_line_counts`` counts hard lines only, so an item's size
depends on how many lines it has) and ``swift`` is absent for ``wrap``. The texts are the
bulletin slips the operator missed for weeks in Oct–Nov 2026 (names left out).
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from worship_deck import announce_suggest as A
from worship_deck import store
from worship_deck.keynote import build as keynote
from worship_deck.lyrics import suggest as S
from worship_deck.parse import ServiceData

FAST = (
    "4. 특별 기도회\n\n11월 1일 부터 금식을 하실 수 있는 분들은 싸인업 시트에 이름을 작정해 주세요.\n"
    "•오전 6:00 - 오후 6:00\n•오후: 600 - 다음 날 오전 6:00"
)
# Nine hard lines: over the 8 that fit BOX at 80pt, so the build would shrink it to 75pt.
LONG = "6. 슈박스\n\n" + "\n".join(f"줄 {i}" for i in range(7))


@pytest.fixture(autouse=True)
def _fake_coretext(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keynote, "_measure_line_counts", lambda reqs: [r["text"].count("\n") + 1 for r in reqs])


def test_resolve_exact_whitespace_flexible_ambiguous_missing() -> None:
    assert A.resolve(FAST, "작정해 주세요") == (FAST.index("작정해"), FAST.index("작정해") + 7)
    text = "아이들과 단순한\n할로윈이 아닌"
    assert A.resolve(text, "단순한 할로윈이") == (5, 13)  # a line break read as a space
    assert A.resolve(FAST, "6:00").startswith("3군데")
    assert A.resolve(FAST, "작성해") == "항목에 없음"


def test_check_item_keeps_exact_old_context_and_diff_in_text_order() -> None:
    edits, errors = A.check_item(FAST, 4, [
        {"kind": "typo", "old": "오후: 600", "new": "오후 6:00", "why": "시각 표기"},
        {"kind": "typo", "old": "1일 부터", "new": "1일부터"},
        {"kind": "typo", "old": "작정해 주세요", "new": "작성해 주세요"},
    ])
    assert errors == []
    assert [e["old"] for e in edits] == ["1일 부터", "작정해 주세요", "오후: 600"]
    first = edits[0]
    assert first["ctx"] == ["특별 기도회\n\n11월 ", " 금식을 하실 수 있는"]  # 12 characters each side
    assert first["diff"] == [["=", "1일"], ["-", " "], ["=", "부터"]]
    assert edits[1]["diff"] == [["=", "작"], ["-", "정"], ["+", "성"], ["=", "해 주세요"]]


def test_check_item_reports_bad_kind_overlap_no_change_and_missing() -> None:
    edits, errors = A.check_item(FAST, 4, [
        {"kind": "fix", "old": "작정해", "new": "작성해"},
        {"kind": "typo", "old": "작정해 주세요", "new": "작성해 주세요"},
        {"kind": "style", "old": "주세요.", "new": "주세요.\n"},  # overlaps the edit above
        {"kind": "typo", "old": "특별 기도회", "new": "특별 기도회"},
        {"kind": "typo", "old": "없는 글", "new": "x"},
    ])
    assert len(edits) == 1
    assert [e.split(": ", 1)[1] for e in errors] == [
        "typo / break / shorten / style 중 하나", "다른 수정과 겹침 — 하나로 합치세요",
        "바뀌는 것이 없음", "항목에 없음",
    ]


def test_apply_edits_skips_style_unless_asked() -> None:
    text = "11/15 (주일) 4:00 PM, 중고등부실에서 수료예배있습니다."
    edits, _ = A.check_item(text, 5, [
        {"kind": "typo", "old": "수료예배있습니다", "new": "수료예배 있습니다"},
        {"kind": "style", "old": "4:00 PM, 중고등부실에서 ", "new": "4:00 PM\n- 장소: 중고등부실\n"},
    ])
    assert A.apply_edits(text, edits, ("typo", "break", "shorten")) == (
        "11/15 (주일) 4:00 PM, 중고등부실에서 수료예배 있습니다.")
    assert A.apply_edits(text, edits) == "11/15 (주일) 4:00 PM\n- 장소: 중고등부실\n수료예배 있습니다."


def test_build_suggestions_measures_before_and_after_and_warns() -> None:
    shorten = {"kind": "shorten", "old": "\n줄 6", "new": "", "why": "중복"}
    records, errors = A.build_suggestions([FAST, LONG], {"announcements": [
        {"item": 1, "edits": [{"kind": "typo", "old": "작정해", "new": "작성해"}]},
        {"item": 2, "edits": [shorten]},
        {"item": 3, "edits": []},
    ]})
    assert [(r["item"], r["pt"], r["pt_after"]) for r in records] == [(1, 80, 80), (2, 75, 80)]
    assert records[1]["title"] == "6. 슈박스" and errors == ["item 3: 교회소식은 2개"]
    # A break that adds lines pushes an item that fit over the box: the report says so.
    _, errors = A.build_suggestions([LONG.replace("\n줄 6", "")], {"announcements": [
        {"item": 1, "edits": [{"kind": "break", "old": "줄 5", "new": "줄\n5"}]}]})
    assert errors == ["⚠ [1] 제안 때문에 80pt에 안 들어감 → 빌드가 75pt로 줄임"]


def test_apply_spec_writes_its_own_key_and_keeps_the_lyric_one(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(store, "RUNS_DIR", tmp_path / "runs")
    store.save("2026-11-08", ServiceData(announcements=[FAST]))
    before = store.path_for("2026-11-08").read_text(encoding="utf-8")
    S.save_section("2026-11-08", "worship_songs", [{"ref": 0}])
    records, errors = A.apply_spec("2026-11-08", {"announcements": [
        {"item": 1, "edits": [{"kind": "typo", "old": "작정해", "new": "작성해"}]}]})
    assert store.path_for("2026-11-08").read_text(encoding="utf-8") == before
    saved = S.load_sidecar("2026-11-08")
    assert saved["worship_songs"] == [{"ref": 0}] and saved["announcements"] == records
    assert errors == [] and records[0]["edits"][0]["new"] == "작성해"
    S.save_section("2026-11-08", "worship_songs", [])  # the lyric step re-run keeps these
    assert S.load_sidecar("2026-11-08")["announcements"] == records


def test_wrap_falls_back_to_hard_lines_without_swift(monkeypatch) -> None:
    def no_swift(*_a, **_k):
        raise FileNotFoundError("swift")

    monkeypatch.setattr(subprocess, "run", no_swift)
    assert A.wrap(["a\n\nb"], 80) == [["a\n", "\n", "b\n"]]


def test_show_marks_soft_wraps_and_flags_items_over_80pt(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(store, "RUNS_DIR", tmp_path / "runs")
    store.save("2026-11-08", ServiceData(announcements=["1. 제목\n\n긴 문장이 슬라이드에서 넘어감", LONG]))
    monkeypatch.setattr(A, "wrap", lambda items, pt: [["1. 제목\n", "\n", "긴 문장이 ", "슬라이드에서 넘어감"],
                                                      [ln + "\n" for ln in LONG.split("\n")]])
    A._show("2026-11-08")
    out = capsys.readouterr().out.splitlines()
    assert out[1] == "[1] 4/8줄" and out[4] == "    긴 문장이  ↩" and out[5] == "    슬라이드에서 넘어감"
    assert out[6] == "[2] 9/8줄 ⚠ 80pt에 안 들어감 → 빌드가 75pt로 줄임 (shorten 제안 필요)"


@pytest.mark.local_only
def test_wrap_lines_swift_matches_the_slide() -> None:
    """The 2026-10-25 title the operator re-broke by hand wraps right after its " / "."""
    if not shutil.which("swift"):
        pytest.skip("needs swift (Xcode Command Line Tools)")
    title = "7. 창립 30주년 기념 영상 사진 자료 수집 / Thanksgiving Day"
    lines = A.wrap([title + "\n\n본문"], 80)[0]
    if lines == [title + "\n", "\n", "본문\n"]:
        pytest.skip("NanumGothicBold not installed")
    assert lines[:2] == ["7. 창립 30주년 기념 영상 사진 자료 수집 / ", "Thanksgiving Day\n"]
    assert json.loads(json.dumps(lines)) == lines
