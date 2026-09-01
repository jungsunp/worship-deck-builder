"""Tests for worship_deck.web.app — health, upload endpoint, mobile page, assemble."""

from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from worship_deck import hymn, library, store
from worship_deck.bible.verses import Verse
from worship_deck.lyrics.transcribe import Song
from worship_deck.parse import ServiceData
from worship_deck.web import app as app_module
from worship_deck.web.app import app

client = TestClient(app)


def test_health_ok() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_index_serves_upload_slots() -> None:
    """One dedicated slot per required source (#109), plus the choir-text editor."""
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.text
    # auto-upload on file select / auto-save choir text — no per-slot submit buttons
    assert "uploadSlot(this, 'bulletin')" in body
    assert "uploadSlot(this, 'sheets')" in body
    assert "uploadSlot(this, 'confession')" in body
    assert 'id="choirText"' in body
    assert "choirChanged()" in body
    # per-slot uploaded-file lists (✓ + name + delete) render inside each slot
    assert 'id="files-bulletin"' in body
    assert 'id="files-sheet"' in body
    assert 'id="files-confession"' in body


def test_upload_bulletin_saves_to_fixed_name(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    resp = client.post(
        "/upload/bulletin", files={"files": ("주보-0531.pdf", b"%PDF-data", "application/pdf")}
    )
    assert resp.status_code == 200
    assert resp.json() == {"saved": ["bulletin.pdf"]}
    assert (tmp_path / "bulletin.pdf").read_bytes() == b"%PDF-data"
    # a second upload replaces the slot
    client.post("/upload/bulletin", files={"files": ("other.pdf", b"%PDF-2", "application/pdf")})
    assert (tmp_path / "bulletin.pdf").read_bytes() == b"%PDF-2"


def test_upload_sheets_keeps_name_order_behind_prefix(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    resp = client.post(
        "/upload/sheets",
        files=[
            ("files", ("01-song.png", b"png1", "image/png")),
            ("files", ("02-song.jpg", b"png2", "image/jpeg")),
        ],
    )
    assert resp.status_code == 200
    assert (tmp_path / "sheet-01-song.png").read_bytes() == b"png1"
    assert (tmp_path / "sheet-02-song.jpg").read_bytes() == b"png2"


def test_upload_confession_replaces_across_extensions(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    client.post("/upload/confession", files={"files": ("a.png", b"old", "image/png")})
    client.post("/upload/confession", files={"files": ("b.jpg", b"new", "image/jpeg")})
    assert not (tmp_path / "confession.png").exists()
    assert (tmp_path / "confession.jpg").read_bytes() == b"new"


def test_upload_rejects_wrong_type_per_slot(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    assert client.post(
        "/upload/bulletin", files={"files": ("sheet.png", b"png", "image/png")}
    ).status_code == 400
    assert client.post(
        "/upload/sheets", files={"files": ("bulletin.pdf", b"pdf", "application/pdf")}
    ).status_code == 400
    assert client.post(
        "/upload/confession", files={"files": ("bulletin.pdf", b"pdf", "application/pdf")}
    ).status_code == 400
    assert client.post(
        "/upload/nope", files={"files": ("a.png", b"png", "image/png")}
    ).status_code == 400


def test_upload_sanitizes_filename(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    resp = client.post("/upload/sheets", files={"files": ("../evil.png", b"x", "image/png")})
    assert resp.status_code == 200
    assert (tmp_path / "sheet-evil.png").read_bytes() == b"x"
    # nothing escaped the inbox dir
    assert not (tmp_path.parent / "evil.png").exists()
    assert not (tmp_path.parent / "sheet-evil.png").exists()


def test_save_choir_text_writes_and_clears(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    text = "제목\n작곡자 작곡\n가사 한 줄"
    assert client.post("/inbox/choir", json={"text": text}).json() == {"saved": True}
    assert (tmp_path / "choir.txt").read_text(encoding="utf-8") == text
    # blank text clears the slot
    assert client.post("/inbox/choir", json={"text": "  \n"}).json() == {"saved": False}
    assert not (tmp_path / "choir.txt").exists()


def test_save_confession_text_writes_and_clears(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    text = "고백곡\n작곡자 작곡\n가사 한 줄"
    assert client.post("/inbox/confession-text", json={"text": text}).json() == {"saved": True}
    assert (tmp_path / "confession.txt").read_text(encoding="utf-8") == text
    # blank text clears the slot
    assert client.post("/inbox/confession-text", json={"text": "  \n"}).json() == {"saved": False}
    assert not (tmp_path / "confession.txt").exists()


def test_upload_sermonsong_replaces_across_extensions(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    client.post("/upload/sermonsong", files={"files": ("a.png", b"old", "image/png")})
    client.post("/upload/sermonsong", files={"files": ("b.jpg", b"new", "image/jpeg")})
    assert not (tmp_path / "sermonsong.png").exists()
    assert (tmp_path / "sermonsong.jpg").read_bytes() == b"new"


def test_upload_sermonsong_rejects_non_image(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    assert client.post(
        "/upload/sermonsong", files={"files": ("bulletin.pdf", b"pdf", "application/pdf")}
    ).status_code == 400


def test_save_sermonsong_text_writes_and_clears(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    text = "설교후곡\n작곡자 작곡\n가사 한 줄"
    assert client.post("/inbox/sermonsong-text", json={"text": text}).json() == {"saved": True}
    assert (tmp_path / "sermonsong.txt").read_text(encoding="utf-8") == text
    # blank text clears the slot
    assert client.post("/inbox/sermonsong-text", json={"text": "  \n"}).json() == {"saved": False}
    assert not (tmp_path / "sermonsong.txt").exists()


def test_sermonsong_image_and_text_are_mutually_exclusive(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    # typing lyrics drops a competing uploaded image ...
    client.post("/upload/sermonsong", files={"files": ("a.png", b"img", "image/png")})
    client.post("/inbox/sermonsong-text", json={"text": "설교후곡\n가사"})
    assert not (tmp_path / "sermonsong.png").exists()
    assert (tmp_path / "sermonsong.txt").exists()
    # ... and uploading an image drops the typed text.
    client.post("/upload/sermonsong", files={"files": ("b.png", b"img", "image/png")})
    assert not (tmp_path / "sermonsong.txt").exists()
    assert (tmp_path / "sermonsong.png").exists()


# ── /inbox ───────────────────────────────────────────────────────────────────────


def test_inbox_lists_files_with_kind(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    (tmp_path / "bulletin.pdf").write_bytes(b"%PDF")
    (tmp_path / "confession.png").write_bytes(b"img")
    (tmp_path / "sheet-1.png").write_bytes(b"pngdata")
    resp = client.get("/inbox")
    assert resp.status_code == 200
    assert resp.json() == {
        "files": [
            {"name": "bulletin.pdf", "size": 4, "kind": "bulletin"},
            {"name": "confession.png", "size": 3, "kind": "confession"},
            {"name": "sheet-1.png", "size": 7, "kind": "sheet"},
        ],
        "choir_text": "",
        "confession_pick": "",
        "confession_text": "",
        "sermonsong_text": "",
    }


def test_inbox_choir_text_excluded_from_files(tmp_path, monkeypatch) -> None:
    """choir.txt has its own textarea UI — it round-trips via choir_text, not the file list."""
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    (tmp_path / "choir.txt").write_text("제목\n가사", encoding="utf-8")
    assert client.get("/inbox").json() == {
        "files": [], "choir_text": "제목\n가사", "confession_pick": "", "confession_text": "",
        "sermonsong_text": "",
    }


def test_inbox_confession_text_excluded_from_files(tmp_path, monkeypatch) -> None:
    """confession.txt has its own textarea UI — round-trips via confession_text, not the file list."""
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    (tmp_path / "confession.txt").write_text("고백곡\n가사", encoding="utf-8")
    assert client.get("/inbox").json() == {
        "files": [], "choir_text": "", "confession_pick": "", "confession_text": "고백곡\n가사",
        "sermonsong_text": "",
    }


def test_inbox_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path / "missing")
    assert client.get("/inbox").json() == {
        "files": [], "choir_text": "", "confession_pick": "", "confession_text": "",
        "sermonsong_text": "",
    }


def test_delete_inbox_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    f = tmp_path / "bulletin.pdf"
    f.write_bytes(b"%PDF")
    resp = client.delete("/inbox/bulletin.pdf")
    assert resp.status_code == 200
    assert not f.exists()


def test_clear_inbox(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    (tmp_path / "bulletin.pdf").write_bytes(b"%PDF")
    (tmp_path / "sheet-a.png").write_bytes(b"png")
    (tmp_path / "choir.txt").write_text("가사", encoding="utf-8")
    resp = client.delete("/inbox")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": 3}
    assert not list(tmp_path.iterdir())


def test_clear_inbox_missing_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path / "missing")
    assert client.delete("/inbox").json() == {"deleted": 0}


def test_delete_missing_is_404(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    assert client.delete("/inbox/nope.pdf").status_code == 404


def test_delete_rejects_traversal(tmp_path, monkeypatch) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setattr(app_module, "INBOX_DIR", inbox)
    outside = tmp_path / "secret.txt"
    outside.write_bytes(b"x")
    # a name carrying a path component is rejected before any unlink
    resp = client.delete("/inbox/..%2Fsecret.txt")
    assert resp.status_code in (400, 404)
    assert outside.exists()


def test_index_shows_inbox_section() -> None:
    assert 'id="inbox"' in client.get("/").text


# ── /assemble ──────────────────────────────────────────────────────────────────
# The heavy steps (Vision OCR + Ollama, ESV) are monkeypatched so these run on CI.
# Starlette's TestClient runs the BackgroundTask before returning, so the assemble
# response already reflects the completed run — no real polling loop needed.


def _fake_data() -> ServiceData:
    """Parsed bulletin: an opening 찬양 row (band name) + a ref-bearing row + a hymn.

    Mirrors parse.parse: the call-to-worship ref is lifted to the top-level field (assemble
    looks up its passage from there, not from the worship_order row).
    """
    return ServiceData(
        date="2026년 5월 31일",
        worship_order=[
            {"part": "찬양", "title": "마라나타", "leader": "", "ref": ""},
            {"part": "예배의 부름", "title": "", "leader": "", "ref": "시 133:1-3"},
        ],
        call_to_worship_ref="시 133:1-3",
        offering_hymn_number="220",
    )


@pytest.fixture
def _assemble_env(tmp_path, monkeypatch):
    """Inbox + runs dir in tmp; parse/transcribe/verses/hymn faked."""
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    monkeypatch.setattr(app_module, "HYMN_DIR", tmp_path / "runs")
    monkeypatch.setattr(store, "RUNS_DIR", tmp_path / "runs")
    (tmp_path / "bulletin.pdf").write_bytes(b"%PDF")
    (tmp_path / "sheet-1.png").write_bytes(b"png")
    monkeypatch.setattr(app_module.parse, "parse", lambda _p: _fake_data())
    monkeypatch.setattr(
        app_module.verses, "lookup_verses",
        lambda ref: [Verse(number=1, korean="한글", english="english")],
    )
    monkeypatch.setattr(
        app_module.hymn, "fetch_hymn_slides",
        lambda number, work_dir, **kw: [work_dir / "slide-1.png", work_dir / "slide-2.png"],
    )


def test_assemble_folds_continuation_sheet(_assemble_env, monkeypatch, tmp_path) -> None:
    """A sheet transcribe flagged as page 2 of the previous song (#213) joins that song's
    fragments (sharpening re-search) instead of becoming a card of its own."""
    (tmp_path / "sheet-2.png").write_bytes(b"png")
    seen: list = []
    sheets = iter([
        [Song(title="주 은혜임을", lines=["1절"], fragments=["앞장 조각"],
              provenance={"source": "gasazip", "song_id": "1"})],
        [Song(title="", fragments=["뒷장 조각"],
              provenance={"source": "ocr", "continuation": True})],
    ])

    def fake(_p, **kw):
        seen.append(kw.get("previous_lines"))
        return next(sheets)

    monkeypatch.setattr(app_module.lyrics_transcribe, "transcribe", fake)
    date = client.post("/assemble").json()["service_date"]

    (song,) = store.load(date).worship_songs
    assert song["fragments"] == ["앞장 조각", "뒷장 조각"]
    assert song["provenance"]["merged_sheets"] == 2
    # The previous song's canonical lyrics are what transcribe compares against.
    assert seen == [None, ["1절"]]


def test_assemble_keeps_titleless_song_that_is_not_a_continuation(
    _assemble_env, monkeypatch
) -> None:
    """2026-07-26 sheet 1 was a separate song Vision couldn't name — it must keep its card
    (operator types the title + 재검색), not vanish into the song before it."""
    monkeypatch.setattr(
        app_module.lyrics_transcribe, "transcribe",
        lambda _p, **kw: [Song(title="", fragments=["조각"], provenance={"source": "ocr"})],
    )
    date = client.post("/assemble").json()["service_date"]
    (song,) = store.load(date).worship_songs
    assert song["title"] == "" and song["provenance"]["source"] == "ocr"


def test_assemble_populates_run(_assemble_env, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        app_module.lyrics_transcribe, "transcribe",
        lambda _p, **kw: [Song(title="주 은혜임을", lines=["1절", "2절"])],
    )
    resp = client.post("/assemble")
    assert resp.status_code == 200
    date = resp.json()["service_date"]
    assert date == "2026-05-31"

    status = client.get(f"/assemble/{date}/status")
    assert status.json()["status"] == "done"

    data = store.load(date)
    assert data.worship_songs == [
        {"title": "주 은혜임을", "lines": ["1절", "2절"], "composer": "",
         "sections": [], "arrangement": "", "arrangement_hint": "", "provenance": {},
         "fragments": [], "candidates": []}
    ]
    assert data.call_to_worship_passage == [
        {"number": 1, "korean": "한글", "english": "english"},
    ]
    assert data.offering_hymn_images == [
        str(tmp_path / "runs" / date / "hymn" / "slide-1.png"),
        str(tmp_path / "runs" / date / "hymn" / "slide-2.png"),
    ]


def test_assemble_also_fetches_the_propresenter_hymn_design(_assemble_env, monkeypatch) -> None:
    """The same hymn again in hymn.PRO_DESIGN, into a subdirectory beside the no-bg pages, so
    propresenter.build can swap the operator's kept pages for it by filename (#179)."""
    monkeypatch.setattr(
        app_module.lyrics_transcribe, "transcribe",
        lambda _p, **kw: [Song(title="주 은혜임을", lines=["1절"])],
    )
    calls: list = []

    def _record(number, work_dir, **kw):
        calls.append((number, work_dir, kw.get("design")))
        return [work_dir / "slide-1.png"]

    monkeypatch.setattr(app_module.hymn, "fetch_hymn_slides", _record)
    date = client.post("/assemble").json()["service_date"]

    assert [c[2] for c in calls] == [None, hymn.PRO_DESIGN]
    assert calls[1][1] == calls[0][1] / hymn.PRO_DESIGN
    # The kept list stays on the no-bg pages — the review grid and Keynote both read it.
    assert store.load(date).offering_hymn_images == [str(calls[0][1] / "slide-1.png")]


def test_assemble_propresenter_design_failure_keeps_the_no_bg_pages(
    _assemble_env, monkeypatch
) -> None:
    """A failed design fetch must not cost us the pages we already have — the .pro just falls
    back to no-bg."""
    monkeypatch.setattr(
        app_module.lyrics_transcribe, "transcribe",
        lambda _p, **kw: [Song(title="주 은혜임을", lines=["1절"])],
    )

    def _boom_on_design(number, work_dir, **kw):
        if kw.get("design"):
            raise RuntimeError("403 forbidden")
        return [work_dir / "slide-1.png"]

    monkeypatch.setattr(app_module.hymn, "fetch_hymn_slides", _boom_on_design)
    date = client.post("/assemble").json()["service_date"]

    assert client.get(f"/assemble/{date}/status").json()["status"] == "done"
    assert len(store.load(date).offering_hymn_images) == 1


def test_assemble_hymn_failure_is_nonfatal(_assemble_env, monkeypatch) -> None:
    monkeypatch.setattr(
        app_module.lyrics_transcribe, "transcribe",
        lambda _p, **kw: [Song(title="주 은혜임을", lines=["1절"])],
    )

    def _boom(number, work_dir, **kw):
        raise RuntimeError("403 forbidden")

    monkeypatch.setattr(app_module.hymn, "fetch_hymn_slides", _boom)

    resp = client.post("/assemble")
    date = resp.json()["service_date"]
    status = client.get(f"/assemble/{date}/status").json()
    # transcribe + verses still succeeded; only the hymn download is soft-failed.
    assert status["status"] == "done"
    assert "220" in status["warning"]
    assert store.load(date).offering_hymn_images == []


def test_assemble_no_bulletin_is_400(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    resp = client.post("/assemble")
    assert resp.status_code == 400
    assert "bulletin" in resp.json()["detail"]


def test_assemble_step_failure_surfaces_as_error(_assemble_env, monkeypatch) -> None:
    def _boom(_p, **kwargs):
        raise RuntimeError("transcription blew up")

    monkeypatch.setattr(app_module.lyrics_transcribe, "transcribe", _boom)
    resp = client.post("/assemble")
    assert resp.status_code == 200  # parse succeeded; the failure is in the async step
    date = resp.json()["service_date"]
    status = client.get(f"/assemble/{date}/status").json()
    assert status["status"] == "error"
    assert "transcription blew up" in status["error"]


def test_assemble_parses_choir_text(_assemble_env, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        app_module.lyrics_transcribe, "transcribe", lambda _p, **kw: [Song(title="찬양곡", lines=["x"])]
    )
    # interior blank line = stanza break (#101) — must survive into choir_song
    (tmp_path / "choir.txt").write_text("제목\n작곡자 작곡\n1절 가사\n\n2절 가사", encoding="utf-8")
    date = client.post("/assemble").json()["service_date"]
    assert store.load(date).choir_song == {
        "title": "제목",
        "lines": ["1절 가사", "", "2절 가사"],
        "composer": "작곡자 작곡",
        "sections": [],
        "arrangement": "",
        "arrangement_hint": "",
        "provenance": {},
        "fragments": [],
        "candidates": [],
    }


def test_assemble_transcribes_confession(_assemble_env, monkeypatch, tmp_path) -> None:
    (tmp_path / "confession.png").write_bytes(b"img")
    monkeypatch.setattr(
        app_module.lyrics_transcribe, "transcribe",
        # basename check — pytest's tmp_path itself contains the test name ("confession")
        lambda p, **kw: [Song(title="아무것도 두려워말라" if Path(p).name.startswith("confession") else "찬양곡", lines=["x"])],
    )
    date = client.post("/assemble").json()["service_date"]
    data = store.load(date)
    assert data.confession_song == {"title": "아무것도 두려워말라", "lines": ["x"], "composer": "",
                                     "sections": [], "arrangement": "", "arrangement_hint": "",
                                     "provenance": {}, "fragments": [], "candidates": []}
    assert [s["title"] for s in data.worship_songs] == ["찬양곡"]  # medley untouched by the slot


# ── confession song library (고백의 찬양 pick + save) ──────────────────────────────


def test_save_and_list_confession_library(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(library, "LIBRARY_DIR", tmp_path / "library")
    song = {"title": "주 은혜임을", "lines": ["1절", "", "2절"], "composer": "작곡가"}
    assert client.post("/library/confession", json=song).json()["title"] == "주 은혜임을"
    songs = client.get("/library/confession").json()["songs"]
    assert songs == [{"slug": "주-은혜임을", "title": "주 은혜임을", "composer": "작곡가"}]


def test_save_confession_library_requires_title(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(library, "LIBRARY_DIR", tmp_path / "library")
    assert client.post("/library/confession", json={"title": "  ", "lines": ["x"]}).status_code == 400


def test_pick_confession_clears_image_and_reports_title(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    monkeypatch.setattr(library, "LIBRARY_DIR", tmp_path / "library")
    slug = library.save_song({"title": "도는찬양", "lines": ["가사"], "composer": ""})
    (tmp_path / "confession.png").write_bytes(b"img")  # an earlier image upload
    assert client.post("/inbox/confession-pick", json={"slug": slug}).json() == {"title": "도는찬양"}
    assert not (tmp_path / "confession.png").exists()  # image and pick are exclusive
    assert (tmp_path / "confession-pick.json").is_file()
    # /inbox surfaces the pick title, not a file row
    inbox = client.get("/inbox").json()
    assert inbox["confession_pick"] == "도는찬양"
    assert inbox["files"] == []


def test_pick_confession_unknown_slug_is_404(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    monkeypatch.setattr(library, "LIBRARY_DIR", tmp_path / "library")
    assert client.post("/inbox/confession-pick", json={"slug": "nope"}).status_code == 404


def test_upload_confession_image_clears_pick(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    monkeypatch.setattr(library, "LIBRARY_DIR", tmp_path / "library")
    slug = library.save_song({"title": "도는찬양", "lines": ["가사"]})
    client.post("/inbox/confession-pick", json={"slug": slug})
    client.post("/upload/confession", files={"files": ("a.png", b"img", "image/png")})
    assert not (tmp_path / "confession-pick.json").exists()  # inverse exclusivity


def test_confession_text_clears_image_and_pick(tmp_path, monkeypatch) -> None:
    """The three confession inputs are mutually exclusive — typing text drops image + pick."""
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    monkeypatch.setattr(library, "LIBRARY_DIR", tmp_path / "library")
    (tmp_path / "confession.png").write_bytes(b"img")
    slug = library.save_song({"title": "도는찬양", "lines": ["가사"]})
    client.post("/inbox/confession-pick", json={"slug": slug})  # this already dropped the image
    (tmp_path / "confession.png").write_bytes(b"img")  # re-add to prove text drops it too
    assert client.post("/inbox/confession-text", json={"text": "고백곡\n가사"}).json() == {"saved": True}
    assert not (tmp_path / "confession.png").exists()
    assert not (tmp_path / "confession-pick.json").exists()
    assert (tmp_path / "confession.txt").is_file()


def test_upload_confession_image_clears_text(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    client.post("/inbox/confession-text", json={"text": "고백곡\n가사"})
    client.post("/upload/confession", files={"files": ("a.png", b"img", "image/png")})
    assert not (tmp_path / "confession.txt").exists()  # inverse exclusivity


def test_pick_confession_clears_text(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    monkeypatch.setattr(library, "LIBRARY_DIR", tmp_path / "library")
    slug = library.save_song({"title": "도는찬양", "lines": ["가사"]})
    client.post("/inbox/confession-text", json={"text": "고백곡\n가사"})
    client.post("/inbox/confession-pick", json={"slug": slug})
    assert not (tmp_path / "confession.txt").exists()  # inverse exclusivity


def test_clear_inbox_drops_pick_but_keeps_library(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    monkeypatch.setattr(library, "LIBRARY_DIR", tmp_path / "library")
    slug = library.save_song({"title": "도는찬양", "lines": ["가사"]})
    client.post("/inbox/confession-pick", json={"slug": slug})
    client.delete("/inbox")
    assert not (tmp_path / "confession-pick.json").exists()  # swept with the rest of the inbox
    assert library.load_song(slug) is not None  # library lives outside the inbox


def test_assemble_uses_library_pick_without_transcribing(_assemble_env, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(library, "LIBRARY_DIR", tmp_path / "library")
    slug = library.save_song({"title": "도는찬양", "lines": ["폴리시된 가사"], "composer": "C"})
    client.post("/inbox/confession-pick", json={"slug": slug})
    # transcribe still runs for the 찬양 medley sheet, but never produces the confession song
    monkeypatch.setattr(
        app_module.lyrics_transcribe, "transcribe", lambda _p, **kw: [Song(title="찬양곡", lines=["x"])]
    )
    date = client.post("/assemble").json()["service_date"]
    data = store.load(date)
    assert data.confession_song == {"title": "도는찬양", "lines": ["폴리시된 가사"], "composer": "C",
                                     "sections": [], "arrangement": ""}
    assert [s["title"] for s in data.worship_songs] == ["찬양곡"]  # medley untouched


def test_assemble_parses_confession_text_without_transcribing(_assemble_env, monkeypatch, tmp_path) -> None:
    """Typed 고백의 찬양 lyrics are parsed like 성가대 — no OCR runs on them."""
    client.post("/inbox/confession-text", json={"text": "고백곡\n작곡자 작곡\n한 줄"})
    # transcribe runs only for the 찬양 medley sheet, never for the typed confession
    monkeypatch.setattr(
        app_module.lyrics_transcribe, "transcribe", lambda _p, **kw: [Song(title="찬양곡", lines=["x"])]
    )
    date = client.post("/assemble").json()["service_date"]
    data = store.load(date)
    assert data.confession_song == {"title": "고백곡", "composer": "작곡자 작곡", "lines": ["한 줄"],
                                     "sections": [], "arrangement": "", "arrangement_hint": "",
                                     "provenance": {}, "fragments": [], "candidates": []}
    assert [s["title"] for s in data.worship_songs] == ["찬양곡"]  # medley untouched by the slot


def test_assemble_parses_sermonsong_text_without_transcribing(_assemble_env, monkeypatch, tmp_path) -> None:
    """Typed 설교후 찬양 lyrics are parsed like 성가대 — no OCR runs on them."""
    client.post("/inbox/sermonsong-text", json={"text": "설교후곡\n작곡자 작곡\n한 줄"})
    monkeypatch.setattr(
        app_module.lyrics_transcribe, "transcribe", lambda _p, **kw: [Song(title="찬양곡", lines=["x"])]
    )
    date = client.post("/assemble").json()["service_date"]
    assert store.load(date).worship_after_sermon == {
        "title": "설교후곡", "composer": "작곡자 작곡", "lines": ["한 줄"],
        "sections": [], "arrangement": "", "arrangement_hint": "", "provenance": {},
        "fragments": [], "candidates": [],
    }


def test_assemble_transcribes_sermonsong_image(_assemble_env, monkeypatch, tmp_path) -> None:
    (tmp_path / "sermonsong.png").write_bytes(b"img")
    monkeypatch.setattr(
        app_module.lyrics_transcribe, "transcribe",
        lambda p, **kw: [Song(title="설교후곡" if Path(p).name.startswith("sermonsong") else "찬양곡", lines=["x"])],
    )
    date = client.post("/assemble").json()["service_date"]
    data = store.load(date)
    assert data.worship_after_sermon["title"] == "설교후곡"
    assert [s["title"] for s in data.worship_songs] == ["찬양곡"]  # medley untouched by the slot


def test_assemble_without_sermonsong_leaves_it_empty(_assemble_env, monkeypatch) -> None:
    """설교후 찬양 is optional — no input means an empty section and no warning."""
    monkeypatch.setattr(
        app_module.lyrics_transcribe, "transcribe", lambda _p, **kw: [Song(title="찬양곡", lines=["x"])]
    )
    date = client.post("/assemble").json()["service_date"]
    assert store.load(date).worship_after_sermon == {}
    assert "설교후" not in (client.get(f"/assemble/{date}/status").json().get("warning") or "")


def test_assemble_warns_on_missing_slots(tmp_path, monkeypatch) -> None:
    """Only the bulletin is required; the other empty slots warn but assemble still finishes."""
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    monkeypatch.setattr(store, "RUNS_DIR", tmp_path / "runs")
    (tmp_path / "bulletin.pdf").write_bytes(b"%PDF")
    monkeypatch.setattr(app_module.parse, "parse", lambda _p: ServiceData(date="2026년 5월 31일"))
    date = client.post("/assemble").json()["service_date"]
    status = client.get(f"/assemble/{date}/status").json()
    assert status["status"] == "done"
    assert "찬양 sheet images" in status["warning"]
    assert "고백의 찬양" in status["warning"]
    assert "성가대" in status["warning"]


def test_assemble_confession_failure_is_nonfatal(_assemble_env, monkeypatch, tmp_path) -> None:
    (tmp_path / "confession.png").write_bytes(b"img")

    def _transcribe(p, **kwargs):
        if Path(p).name.startswith("confession"):
            raise RuntimeError("transcription blew up")
        return [Song(title="찬양곡", lines=["x"])]

    monkeypatch.setattr(app_module.lyrics_transcribe, "transcribe", _transcribe)
    date = client.post("/assemble").json()["service_date"]
    status = client.get(f"/assemble/{date}/status").json()
    assert status["status"] == "done"
    assert "고백의 찬양" in status["warning"]
    assert store.load(date).confession_song == {}


def test_assemble_status_rejects_bad_date() -> None:
    assert client.get("/assemble/not-a-date/status").status_code == 400


# ── #105: re-assemble warns + preserves review edits ──────────────────────────


def _fake_transcribe(monkeypatch, *titles) -> None:
    monkeypatch.setattr(
        app_module.lyrics_transcribe, "transcribe",
        lambda _p, **kw: [Song(title=t, lines=["x"]) for t in titles],
    )


def test_first_assemble_does_not_need_confirm(_assemble_env, monkeypatch) -> None:
    _fake_transcribe(monkeypatch, "song A")
    body = client.post("/assemble").json()
    assert "needs_confirm" not in body
    assert "status_url" in body


def test_reassemble_existing_run_needs_confirm_and_preserves_store(_assemble_env, monkeypatch) -> None:
    _fake_transcribe(monkeypatch, "song A")
    date = client.post("/assemble").json()["service_date"]
    before = store.path_for(date).read_text(encoding="utf-8")

    body = client.post("/assemble").json()
    assert body["service_date"] == date
    assert body["needs_confirm"] is True
    assert body["kept"] == []  # nothing edited yet
    # the warning short-circuits before any save — the stored run is untouched
    assert store.path_for(date).read_text(encoding="utf-8") == before


def test_reassemble_confirm_lists_kept_and_refreshed_sections(_assemble_env, monkeypatch, tmp_path) -> None:
    _fake_transcribe(monkeypatch, "song A")
    (tmp_path / "choir.txt").write_text("제목\n작곡자 작곡\n가사 한 줄", encoding="utf-8")
    date = client.post("/assemble").json()["service_date"]
    run = client.get(f"/runs/{date}").json()
    run["worship_songs"][0]["lines"] = ["operator edit"]
    run["offering_hymn_verses"] = [1, 3]
    client.put(f"/runs/{date}", json=run)
    # the choir text is gone by re-assemble time → its parsed song is carried over, not refreshed
    (tmp_path / "choir.txt").unlink()

    body = client.post("/assemble").json()
    kept, refresh = body["kept"], body["refresh"]
    # kept lists the operator's edits plus the input-less carry-overs
    assert "성가대 choir lyrics" in kept
    assert "봉헌 verse picks (1, 3)" in kept
    assert "찬양 songs (edited lyrics/order)" in kept
    # refresh lists the not-edited sections, and never an edited or input-less one
    assert "교회소식 announcements (re-parsed)" in refresh
    assert not any("songs" in r for r in refresh)  # 찬양 was edited → not refreshed
    assert not any("성가대" in r for r in refresh)
    assert not any("고백" in r for r in refresh)  # no confession image in inbox


def test_reassemble_refreshes_unedited_choir_from_inbox_text(_assemble_env, monkeypatch, tmp_path) -> None:
    _fake_transcribe(monkeypatch, "song A")
    (tmp_path / "choir.txt").write_text("제목\n작곡자 작곡\n가사 한 줄", encoding="utf-8")
    date = client.post("/assemble").json()["service_date"]
    assert store.load(date).choir_song["lines"] == ["가사 한 줄"]

    (tmp_path / "choir.txt").write_text("제목\n작곡자 작곡\n고친 가사", encoding="utf-8")
    body = client.post("/assemble").json()
    assert "성가대 choir lyrics (re-parsed from inbox text)" in body["refresh"]
    assert client.post("/assemble?confirm=1").status_code == 200
    assert store.load(date).choir_song["lines"] == ["고친 가사"]


def test_reassemble_carries_over_choir_when_inbox_text_gone(_assemble_env, monkeypatch, tmp_path) -> None:
    _fake_transcribe(monkeypatch, "song A")
    (tmp_path / "choir.txt").write_text("제목\n작곡자 작곡\n가사 한 줄", encoding="utf-8")
    date = client.post("/assemble").json()["service_date"]
    run = client.get(f"/runs/{date}").json()
    run["offering_hymn_verses"] = [1, 3]
    client.put(f"/runs/{date}", json=run)
    (tmp_path / "choir.txt").unlink()

    assert client.post("/assemble?confirm=1").status_code == 200
    saved = store.load(date)
    assert saved.choir_song["title"] == "제목"
    assert saved.offering_hymn_verses == [1, 3]


def test_reassemble_preserves_edited_choir_despite_new_inbox_text(_assemble_env, monkeypatch, tmp_path) -> None:
    _fake_transcribe(monkeypatch, "song A")
    (tmp_path / "choir.txt").write_text("제목\n작곡자 작곡\n가사 한 줄", encoding="utf-8")
    date = client.post("/assemble").json()["service_date"]
    run = client.get(f"/runs/{date}").json()
    run["choir_song"]["lines"] = ["operator edit"]  # marks choir_song edited
    client.put(f"/runs/{date}", json=run)

    assert client.post("/assemble?confirm=1").status_code == 200
    assert store.load(date).choir_song["lines"] == ["operator edit"]


def test_reassemble_preserves_dropped_hymn_slides_same_number(_assemble_env, monkeypatch) -> None:
    # Operator drops a 봉헌 slide (#108); a re-assemble of the same hymn must keep the kept subset
    # rather than re-download all slides and reselect every verse.
    _fake_transcribe(monkeypatch, "song A")
    date = client.post("/assemble").json()["service_date"]
    slides = store.load(date).offering_hymn_images
    assert len(slides) == 2
    run = client.get(f"/runs/{date}").json()
    run["offering_hymn_images"] = [slides[0]]  # dropped slide-2
    client.put(f"/runs/{date}", json=run)

    body = client.post("/assemble").json()
    assert not any("봉헌 hymn slide images" in r for r in body["refresh"])
    assert client.post("/assemble?confirm=1").status_code == 200
    assert client.get(f"/assemble/{date}/status").json()["status"] == "done"
    assert store.load(date).offering_hymn_images == [slides[0]]


def test_reassemble_refetches_hymn_slides_when_number_changes(_assemble_env, monkeypatch) -> None:
    # A different hymn in the re-parsed bulletin re-downloads all slides (the old kept subset is
    # meaningless for a new hymn) and lists them as refreshed in the confirm dialog.
    _fake_transcribe(monkeypatch, "song A")
    date = client.post("/assemble").json()["service_date"]
    run = client.get(f"/runs/{date}").json()
    run["offering_hymn_images"] = [store.load(date).offering_hymn_images[0]]
    client.put(f"/runs/{date}", json=run)
    # next parse yields a different 봉헌 hymn number
    monkeypatch.setattr(
        app_module.parse, "parse", lambda _p: replace(_fake_data(), offering_hymn_number="221")
    )

    body = client.post("/assemble").json()
    assert any("봉헌 hymn slide images" in r for r in body["refresh"])
    assert client.post("/assemble?confirm=1").status_code == 200
    assert len(store.load(date).offering_hymn_images) == 2  # re-downloaded, all slides


def test_reassemble_preserves_edited_songs_refreshes_unedited(_assemble_env, monkeypatch) -> None:
    _fake_transcribe(monkeypatch, "song A")
    date = client.post("/assemble").json()["service_date"]
    run = client.get(f"/runs/{date}").json()
    run["worship_songs"][0]["lines"] = ["operator edit"]  # marks worship_songs edited
    client.put(f"/runs/{date}", json=run)

    # a corrected bulletin + a different transcription would overwrite if not preserved
    monkeypatch.setattr(
        app_module.parse, "parse", lambda _p: replace(_fake_data(), announcements=["1. new notice"])
    )
    _fake_transcribe(monkeypatch, "song B")
    assert client.post("/assemble?confirm=1").status_code == 200

    saved = store.load(date)
    assert saved.worship_songs[0]["lines"] == ["operator edit"]  # edited → preserved
    assert saved.worship_songs[0]["title"] == "song A"
    assert saved.announcements == ["1. new notice"]  # unedited → refreshed


def test_reassemble_preserves_extra_sermon_refs(_assemble_env, monkeypatch) -> None:
    _fake_transcribe(monkeypatch, "song A")
    date = client.post("/assemble").json()["service_date"]
    run = client.get(f"/runs/{date}").json()
    run["sermon_extra_refs"] = ["요 3:16"]  # looked up via the _assemble_env verses mock
    client.put(f"/runs/{date}", json=run)

    body = client.post("/assemble").json()
    assert "추가 말씀 구절 (요 3:16)" in body["kept"]
    assert client.post("/assemble?confirm=1").status_code == 200

    saved = store.load(date)
    assert saved.sermon_extra_refs == ["요 3:16"]
    assert saved.sermon_extra_passages == [[{"number": 1, "korean": "한글", "english": "english"}]]


def test_reassemble_preserves_edited_announcements_refreshes_songs(_assemble_env, monkeypatch) -> None:
    monkeypatch.setattr(
        app_module.parse, "parse", lambda _p: replace(_fake_data(), announcements=["1. orig"])
    )
    _fake_transcribe(monkeypatch, "song A")
    date = client.post("/assemble").json()["service_date"]
    run = client.get(f"/runs/{date}").json()
    run["announcements"] = ["1. operator edit"]  # marks announcements edited
    client.put(f"/runs/{date}", json=run)

    _fake_transcribe(monkeypatch, "song B")
    assert client.post("/assemble?confirm=1").status_code == 200

    saved = store.load(date)
    assert saved.announcements == ["1. operator edit"]  # edited → preserved
    assert [s["title"] for s in saved.worship_songs] == ["song B"]  # unedited → refreshed


# ── review: /review, /runs ───────────────────────────────────────────────────────


def _fake_run() -> ServiceData:
    """An assembled run: a worship-order skeleton + the section content in top-level fields."""
    return ServiceData(
        date="2026년 5월 31일",
        worship_order=[
            {"part": "찬양", "title": "마라나타", "leader": "", "ref": ""},
            {"part": "찬양", "title": "나의 영원하신 기업", "leader": "성가대", "ref": ""},
            {"part": "예배의 부름", "title": "", "leader": "", "ref": "시 133:1-3"},
        ],
        worship_songs=[
            {"title": "주 은혜임을", "lines": ["1절", "2절"], "composer": ""},
            {"title": "마라나타", "lines": ["a", "b"], "composer": ""},
        ],
        call_to_worship_passage=[{"number": 1, "korean": "한글", "english": "english"}],
        call_to_worship_ref="시 133:1-3",
        offering_hymn_number="220",
        offering_hymn_title="피난처 있으니",
    )


@pytest.fixture
def _runs(tmp_path, monkeypatch) -> str:
    """Runs dir in tmp; return a seeded service date."""
    monkeypatch.setattr(store, "RUNS_DIR", tmp_path / "runs")
    return "2026-05-31"


def test_list_runs_newest_first(_runs, tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)  # list_runs probes CWD-relative data/drafts/ for `pdfs`
    store.save("2026-05-31", _fake_run())
    store.save("2026-06-07", _fake_run())
    assert client.get("/runs").json() == {"runs": ["2026-06-07", "2026-05-31"], "pdfs": []}


def test_list_runs_empty(_runs) -> None:
    assert client.get("/runs").json() == {"runs": [], "pdfs": []}


def test_list_runs_pdfs_lists_built_drafts(_runs, tmp_path, monkeypatch) -> None:
    """A run whose draft PDF exists on disk is listed in `pdfs` for the /history link (#102)."""
    monkeypatch.chdir(tmp_path)  # list_runs probes CWD-relative data/drafts/ (mirrors draft.pdf)
    store.save("2026-05-31", _fake_run())
    store.save("2026-06-07", _fake_run())
    drafts = tmp_path / "data" / "drafts"
    drafts.mkdir(parents=True)
    (drafts / "draft-2026-06-07.pdf").write_bytes(b"%PDF-1.4 stub")
    assert client.get("/runs").json() == {
        "runs": ["2026-06-07", "2026-05-31"],
        "pdfs": ["2026-06-07"],
    }


def test_index_shows_runs_section() -> None:
    assert 'id="runs"' in client.get("/").text


def test_get_run_returns_saved_data(_runs) -> None:
    store.save(_runs, _fake_run())
    resp = client.get(f"/runs/{_runs}")
    assert resp.status_code == 200
    assert resp.json() == asdict(_fake_run())


def test_get_run_404_when_missing(_runs) -> None:
    assert client.get(f"/runs/{_runs}").status_code == 404


def test_get_run_400_bad_date() -> None:
    assert client.get("/runs/not-a-date").status_code == 400


def test_put_run_persists_edits(_runs) -> None:
    store.save(_runs, _fake_run())
    run = client.get(f"/runs/{_runs}").json()
    # reorder the two medley songs, fix a lyric line break, pick hymn verses
    run["worship_songs"].reverse()
    run["worship_songs"][0]["lines"] = ["new line 1", "new line 2"]
    run["offering_hymn_verses"] = [1, 3]
    assert client.put(f"/runs/{_runs}", json=run).status_code == 200

    saved = store.load(_runs)
    songs = saved.worship_songs
    assert [s["title"] for s in songs] == ["마라나타", "주 은혜임을"]
    assert songs[0]["lines"] == ["new line 1", "new line 2"]
    assert saved.offering_hymn_verses == [1, 3]


def test_put_run_persists_added_and_deleted_songs(_runs) -> None:
    """＋ 곡 / ✕ edit the medley list itself, not just its lyrics (#231)."""
    store.save(_runs, _fake_run())
    run = client.get(f"/runs/{_runs}").json()
    del run["worship_songs"][0]
    run["worship_songs"].append(
        {"title": "", "lines": [], "composer": "", "sections": [], "arrangement": "",
         "arrangement_hint": "", "provenance": {"source": "added"},
         "fragments": [], "candidates": []}
    )
    assert client.put(f"/runs/{_runs}", json=run).status_code == 200

    saved = store.load(_runs)
    assert [s["title"] for s in saved.worship_songs] == ["마라나타", ""]
    assert saved.worship_songs[1]["provenance"] == {"source": "added"}
    # marked edited so a later re-assemble doesn't resurrect the deleted song (#105)
    assert "worship_songs" in saved.edited_fields


def test_put_run_persists_song_arrangement(_runs) -> None:
    # The labeled sections + play-order string and OCR hint survive PUT -> store.load (#113).
    store.save(_runs, _fake_run())
    run = client.get(f"/runs/{_runs}").json()
    run["worship_songs"][0]["sections"] = [
        {"label": "V1", "lines": ["a", "b"]},
        {"label": "C", "lines": ["c"]},
    ]
    run["worship_songs"][0]["arrangement"] = "V1 C C"
    run["worship_songs"][0]["arrangement_hint"] = "V-C-V-Cx2"
    assert client.put(f"/runs/{_runs}", json=run).status_code == 200

    song = store.load(_runs).worship_songs[0]
    assert song["sections"] == [
        {"label": "V1", "lines": ["a", "b"]},
        {"label": "C", "lines": ["c"]},
    ]
    assert song["arrangement"] == "V1 C C"
    assert song["arrangement_hint"] == "V-C-V-Cx2"


def test_put_run_tracks_edited_fields(_runs) -> None:
    store.save(_runs, _fake_run())
    run = client.get(f"/runs/{_runs}").json()
    # a no-op round-trip marks nothing
    client.put(f"/runs/{_runs}", json=run)
    assert store.load(_runs).edited_fields == []
    # a real edit marks exactly that field (so a later re-assemble preserves it, #105)
    run["worship_songs"][0]["lines"] = ["changed"]
    client.put(f"/runs/{_runs}", json=run)
    assert store.load(_runs).edited_fields == ["worship_songs"]


def test_put_run_400_bad_date() -> None:
    assert client.put("/runs/not-a-date", json={}).status_code == 400


def test_put_run_tracks_choir_and_confession_edits(_runs) -> None:
    store.save(_runs, replace(
        _fake_run(),
        choir_song={"title": "성가", "lines": ["a"], "composer": ""},
        confession_song={"title": "고백", "lines": ["b"], "composer": ""},
    ))
    run = client.get(f"/runs/{_runs}").json()
    run["choir_song"]["lines"] = ["a fixed"]
    run["confession_song"]["lines"] = ["b fixed"]
    client.put(f"/runs/{_runs}", json=run)
    assert store.load(_runs).edited_fields == ["choir_song", "confession_song"]


def test_put_run_tracks_sermonsong_edits(_runs) -> None:
    store.save(_runs, replace(
        _fake_run(), worship_after_sermon={"title": "설교후", "lines": ["a"], "composer": ""},
    ))
    run = client.get(f"/runs/{_runs}").json()
    run["worship_after_sermon"]["lines"] = ["a fixed"]
    client.put(f"/runs/{_runs}", json=run)
    assert store.load(_runs).edited_fields == ["worship_after_sermon"]


def test_put_run_normalizes_untouched_optional_song(_runs) -> None:
    """The review UI seeds an empty V1 card; an untouched 설교후 찬양 must normalize back to {} so
    it isn't flagged as an edit (and so the build skips it)."""
    store.save(_runs, _fake_run())  # worship_after_sermon defaults to {}
    run = client.get(f"/runs/{_runs}").json()
    # what the seeded-but-untouched editor round-trips: an empty V1 card, blank title/composer
    run["worship_after_sermon"] = {
        "title": "", "composer": "", "lines": [],
        "sections": [{"label": "V1", "lines": []}], "arrangement": "", "arrangement_hint": "",
    }
    client.put(f"/runs/{_runs}", json=run)
    saved = store.load(_runs)
    assert saved.worship_after_sermon == {}
    assert "worship_after_sermon" not in saved.edited_fields


def test_put_run_looks_up_changed_extra_refs(_runs, monkeypatch) -> None:
    store.save(_runs, _fake_run())
    calls: list[str] = []

    def _fake_lookup(ref):
        calls.append(ref)
        return [Verse(number=16, korean="한글", english="english")]

    monkeypatch.setattr(app_module.verses, "lookup_verses", _fake_lookup)
    run = client.get(f"/runs/{_runs}").json()
    # whitespace/empties normalized, incl. typed spaces around ':' and '-' in ranges
    run["sermon_extra_refs"] = ["요 3:16", " 롬 8:1-4 ", "시 4: 15 - 20", ""]
    body = client.put(f"/runs/{_runs}", json=run).json()
    assert "warnings" not in body
    assert calls == ["요 3:16", "롬 8:1-4", "시 4:15-20"]

    saved = store.load(_runs)
    assert saved.sermon_extra_refs == ["요 3:16", "롬 8:1-4", "시 4:15-20"]
    assert saved.sermon_extra_passages == [
        [{"number": 16, "korean": "한글", "english": "english"}],
        [{"number": 16, "korean": "한글", "english": "english"}],
        [{"number": 16, "korean": "한글", "english": "english"}],
    ]
    # pure-human field (like offering_hymn_verses) — not tracked as an edit
    assert saved.edited_fields == []

    # saving again with unchanged refs makes no lookup calls and keeps the passages
    calls.clear()
    client.put(f"/runs/{_runs}", json=client.get(f"/runs/{_runs}").json())
    assert calls == []
    assert store.load(_runs).sermon_extra_passages == saved.sermon_extra_passages


def test_put_run_failed_extra_ref_warns_and_saves(_runs, monkeypatch) -> None:
    store.save(_runs, _fake_run())

    def _fake_lookup(ref):
        if ref == "요 99:1":
            raise ValueError("no such chapter")
        return [Verse(number=1, korean="한글", english="english")]

    monkeypatch.setattr(app_module.verses, "lookup_verses", _fake_lookup)
    run = client.get(f"/runs/{_runs}").json()
    run["sermon_extra_refs"] = ["요 99:1", "요 3:16"]
    resp = client.put(f"/runs/{_runs}", json=run)
    assert resp.status_code == 200
    warnings = resp.json()["warnings"]
    assert len(warnings) == 1 and "요 99:1" in warnings[0]

    # the failed ref keeps its slot with an empty passage (build skips it); the rest saved
    saved = store.load(_runs)
    assert saved.sermon_extra_passages == [
        [],
        [{"number": 1, "korean": "한글", "english": "english"}],
    ]


def test_choir_paste_endpoint_removed(_runs) -> None:
    store.save(_runs, _fake_run())
    assert client.post(f"/runs/{_runs}/choir", json={"text": "제목\n가사"}).status_code == 404


def test_review_page_has_confession_editor_and_no_paste_box() -> None:
    body = client.get("/review/2026-05-31").text
    assert "고백의찬양" in body  # confession row predicate
    assert "renderConfession" in body
    assert "붙여넣기" not in body  # the old choir paste box is gone
    assert "attachChoir" not in body


def test_review_page_has_labeled_song_editors() -> None:
    """고백/설교후 찬양 share the V1/C section-card editor (renderLabeledSong + songByRef)."""
    body = client.get("/review/2026-05-31").text
    assert "renderSermonSong" in body
    assert "renderLabeledSong" in body
    assert "songByRef" in body


def test_review_page_can_add_and_delete_medley_songs() -> None:
    """찬양 medley list is editable, and an added song carries the 'added' provenance (#231)."""
    body = client.get("/review/2026-05-31").text
    assert "function addSong" in body
    assert "function deleteSong" in body
    assert "'added'" in body


# ── /runs/{date}/hymn (봉헌 slide grid, #84/#108) ─────────────────────────────


def _seed_hymn_pngs(tmp_path, monkeypatch, date, names) -> list[str]:
    """Write fake hymn PNGs under HYMN_DIR/<date>/hymn/; return their full-path strings."""
    monkeypatch.setattr(app_module, "HYMN_DIR", tmp_path / "runs")
    hymn_dir = tmp_path / "runs" / date / "hymn"
    hymn_dir.mkdir(parents=True)
    paths = []
    for n in names:
        p = hymn_dir / n
        p.write_bytes(b"\x89PNG")
        paths.append(str(p))
    return paths


def test_list_hymn_slides(_runs, tmp_path, monkeypatch) -> None:
    paths = _seed_hymn_pngs(tmp_path, monkeypatch, _runs, ["slide-1.png", "slide-2.png", "slide-3.png"])
    assert client.get(f"/runs/{_runs}/hymn").json() == {"images": paths}


def test_list_hymn_slides_empty_when_no_dir(_runs, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "HYMN_DIR", tmp_path / "runs")
    assert client.get(f"/runs/{_runs}/hymn").json() == {"images": []}


def test_list_hymn_slides_400_bad_date() -> None:
    assert client.get("/runs/not-a-date/hymn").status_code == 400


def test_get_hymn_slide_serves_file(_runs, tmp_path, monkeypatch) -> None:
    _seed_hymn_pngs(tmp_path, monkeypatch, _runs, ["slide-1.png"])
    resp = client.get(f"/runs/{_runs}/hymn/slide-1.png")
    assert resp.status_code == 200
    assert resp.content == b"\x89PNG"


def test_get_hymn_slide_blocks_traversal(_runs, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "HYMN_DIR", tmp_path / "runs")
    (tmp_path / "runs" / _runs).mkdir(parents=True)
    (tmp_path / "runs" / _runs / "secret.png").write_bytes(b"secret")  # one level above hymn/
    # The single-segment {name} route + Path(name).name guard prevent escaping the hymn dir.
    assert client.get(f"/runs/{_runs}/hymn/..%2fsecret.png").status_code != 200


def test_get_hymn_slide_404_when_missing(_runs, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "HYMN_DIR", tmp_path / "runs")
    assert client.get(f"/runs/{_runs}/hymn/nope.png").status_code == 404


def test_draft_pdf_serves_file(_runs, tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)  # endpoint reads CWD-relative data/drafts/ (#23)
    drafts = tmp_path / "data" / "drafts"
    drafts.mkdir(parents=True)
    (drafts / f"draft-{_runs}.pdf").write_bytes(b"%PDF-1.4 stub")
    resp = client.get(f"/runs/{_runs}/draft.pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content == b"%PDF-1.4 stub"


def test_draft_pdf_404_when_not_built(_runs, tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert client.get(f"/runs/{_runs}/draft.pdf").status_code == 404


def test_draft_pdf_400_bad_date() -> None:
    assert client.get("/runs/not-a-date/draft.pdf").status_code == 400


def test_put_run_persists_pruned_hymn_images(_runs, tmp_path, monkeypatch) -> None:
    paths = _seed_hymn_pngs(tmp_path, monkeypatch, _runs, ["slide-1.png", "slide-2.png", "slide-3.png"])
    store.save(_runs, replace(_fake_run(), offering_hymn_images=paths))
    run = client.get(f"/runs/{_runs}").json()
    run["offering_hymn_images"] = [paths[0], paths[2]]  # operator dropped slide-2
    assert client.put(f"/runs/{_runs}", json=run).status_code == 200
    assert store.load(_runs).offering_hymn_images == [paths[0], paths[2]]


def test_review_page_served() -> None:
    resp = client.get("/review/2026-05-31")
    assert resp.status_code == 200
    assert 'id="order"' in resp.text


def test_index_links_to_review() -> None:
    assert "/review/" in client.get("/").text


def test_history_page_served() -> None:
    resp = client.get("/history")
    assert resp.status_code == 200
    assert 'id="history"' in resp.text


# ── /runs/{date}/build (Generate) ────────────────────────────────────────────
# pipeline.run drives real Keynote (local_only); monkeypatch it + the `open` so these run on CI.
# Starlette's TestClient runs the BackgroundTask before returning, so status is terminal.


def test_build_runs_pipeline_and_opens(_runs, monkeypatch) -> None:
    store.save(_runs, _fake_run())
    opened: list = []
    exported: list = []
    monkeypatch.setattr(app_module.pipeline, "run", lambda d, t: f"/tmp/draft-{d}.key")
    monkeypatch.setattr(app_module.keynote_build, "export_pdf", lambda p: exported.append(p))
    monkeypatch.setattr(app_module.subprocess, "run", lambda *a, **kw: opened.append(a))

    resp = client.post(f"/runs/{_runs}/build")
    assert resp.status_code == 200
    assert resp.json()["status_url"] == f"/runs/{_runs}/build/status"

    status = client.get(f"/runs/{_runs}/build/status").json()
    assert status["status"] == "done"
    assert status["path"] == f"/tmp/draft-{_runs}.key"
    assert exported == [f"/tmp/draft-{_runs}.pdf"]  # PDF exported from the built draft (#23)
    assert status["pdf"] == f"/runs/{_runs}/draft.pdf"
    assert opened and opened[0][0] == ["open", f"/tmp/draft-{_runs}.key"]


def test_build_pdf_export_failure_is_nonfatal(_runs, monkeypatch) -> None:
    """A failed PDF export (#23) must not flip a successful build to error; just no preview link."""
    store.save(_runs, _fake_run())
    monkeypatch.setattr(app_module.pipeline, "run", lambda d, t: f"/tmp/draft-{d}.key")
    monkeypatch.setattr(app_module.subprocess, "run", lambda *a, **kw: None)

    def _boom(_p):
        raise RuntimeError("keynote wedged")

    monkeypatch.setattr(app_module.keynote_build, "export_pdf", _boom)
    client.post(f"/runs/{_runs}/build")
    status = client.get(f"/runs/{_runs}/build/status").json()
    assert status["status"] == "done"
    assert status["pdf"] is None


def test_build_missing_run_is_404(_runs) -> None:
    assert client.post(f"/runs/{_runs}/build").status_code == 404


def test_build_refuses_song_left_without_lyrics(_runs, monkeypatch) -> None:
    """A gasazip miss the operator never resolved would ship blank lyric slides (#213)."""
    data = _fake_run()
    data.worship_songs[1] = {"title": "말씀앞에서", "lines": [], "provenance": {"source": "ocr"}}
    store.save(_runs, data)
    monkeypatch.setattr(app_module.pipeline, "run", lambda d, t: pytest.fail("must not build"))

    resp = client.post(f"/runs/{_runs}/build")
    assert resp.status_code == 400
    assert "말씀앞에서" in resp.json()["detail"]


def test_build_refuses_added_song_left_without_lyrics(_runs, monkeypatch) -> None:
    """A ＋ 곡 the operator never filled in would ship a title-only slide unit (#231)."""
    data = _fake_run()
    data.worship_songs.append({"title": "새 찬양", "lines": [], "provenance": {"source": "added"}})
    store.save(_runs, data)
    monkeypatch.setattr(app_module.pipeline, "run", lambda d, t: pytest.fail("must not build"))

    resp = client.post(f"/runs/{_runs}/build")
    assert resp.status_code == 400
    assert "새 찬양" in resp.json()["detail"]


def test_build_allows_added_song_the_operator_typed_lyrics_into(_runs, monkeypatch) -> None:
    """Provenance stays "added" after typing the lyrics in — the lyrics being there is what matters."""
    data = _fake_run()
    data.worship_songs.append(
        {"title": "새 찬양", "lines": ["직접 입력한 가사"], "provenance": {"source": "added"}}
    )
    store.save(_runs, data)
    monkeypatch.setattr(app_module.pipeline, "run", lambda d, t: "/tmp/draft.key")

    assert client.post(f"/runs/{_runs}/build").status_code == 200


def test_build_allows_a_miss_the_operator_typed_lyrics_into(_runs, monkeypatch) -> None:
    """Provenance stays "ocr" after hand-editing — the lyrics being there is what matters."""
    data = _fake_run()
    data.worship_songs[1] = {"title": "말씀앞에서", "lines": ["직접 입력한 가사"],
                             "provenance": {"source": "ocr"}}
    store.save(_runs, data)
    monkeypatch.setattr(app_module.pipeline, "run", lambda d, t: f"/tmp/draft-{d}.key")
    monkeypatch.setattr(app_module.keynote_build, "export_pdf", lambda p: None)
    monkeypatch.setattr(app_module.subprocess, "run", lambda *a, **kw: None)
    assert client.post(f"/runs/{_runs}/build").status_code == 200


def test_build_records_error(_runs, monkeypatch) -> None:
    store.save(_runs, _fake_run())

    def _boom(_d, _t):
        raise RuntimeError("keynote wedged")

    monkeypatch.setattr(app_module.pipeline, "run", _boom)
    client.post(f"/runs/{_runs}/build")
    status = client.get(f"/runs/{_runs}/build/status").json()
    assert status["status"] == "error"
    assert "keynote wedged" in status["error"]


def test_build_pro_target_skips_the_pdf_and_opens_the_bundle(_runs, monkeypatch) -> None:
    """The ProPresenter button runs the same reviewed run through the .pro builder (#180).

    No PDF preview: there is no open document to export one from, and the phone can't render a
    .probundle either — the status just names the file `open` handed to ProPresenter.
    """
    store.save(_runs, _fake_run())
    opened: list = []
    targets: list = []

    def _run(d, t):
        targets.append(t)
        return f"/tmp/draft-{d}.probundle"

    monkeypatch.setattr(app_module.pipeline, "run", _run)
    monkeypatch.setattr(
        app_module.keynote_build, "export_pdf", lambda p: pytest.fail("no PDF for a .pro")
    )
    monkeypatch.setattr(app_module.subprocess, "run", lambda *a, **kw: opened.append(a))

    assert client.post(f"/runs/{_runs}/build?target=pro").status_code == 200
    assert targets == ["pro"]
    status = client.get(f"/runs/{_runs}/build/status").json()
    assert status["status"] == "done"
    assert status["target"] == "pro"
    assert status["path"] == f"/tmp/draft-{_runs}.probundle"
    assert status["pdf"] is None
    assert opened and opened[0][0] == ["open", f"/tmp/draft-{_runs}.probundle"]


def test_build_rejects_an_unknown_target(_runs, monkeypatch) -> None:
    store.save(_runs, _fake_run())
    monkeypatch.setattr(app_module.pipeline, "run", lambda d, t: pytest.fail("must not build"))
    resp = client.post(f"/runs/{_runs}/build?target=powerpoint")
    assert resp.status_code == 400
    assert "keynote" in resp.json()["detail"]


def test_review_page_has_both_build_buttons() -> None:
    """Keynote stays the fallback that runs the service; ProPresenter is the migration target."""
    page = client.get("/review/2026-05-31").text
    assert 'id="generate"' in page
    assert 'id="generatePro"' in page


# ---------------------------------------------------------------------------
# Re-search (#203): per-song title correction + gasazip candidate picker
# ---------------------------------------------------------------------------

def test_research_scores_stored_fragments(_runs, monkeypatch) -> None:
    """POST /research re-runs the lookup for one song, scoring the corrected title against the
    song's persisted OCR fragments, and returns candidates with a short preview for picking."""
    run = _fake_run()
    run.worship_songs[0]["fragments"] = ["보좌앞에 지금가오니"]
    store.save(_runs, run)
    seen = {}

    def fake_scored(title, fragments, **kw):
        seen["title"], seen["fragments"] = title, fragments
        return [
            app_module.lyrics_online.Candidate(
                song_id="111", title="보좌 앞으로", artist="찬미워십",
                lines=["주님의보혈", "", "받아주소서"], cand_cov=0.9, ocr_cov=0.8,
            )
        ]

    monkeypatch.setattr(app_module.lyrics_online, "search_scored", fake_scored)
    r = client.post(f"/runs/{_runs}/research", json={"ref": "0", "title": "보좌 앞으로"})
    assert r.status_code == 200
    assert seen == {"title": "보좌 앞으로", "fragments": ["보좌앞에 지금가오니"]}
    assert r.json()["scored"] is True  # song has stored fragments → match %s are meaningful
    assert r.json()["candidates"] == [
        {"song_id": "111", "title": "보좌 앞으로", "artist": "찬미워십",
         "cand_cov": 0.9, "ocr_cov": 0.8, "preview": ["주님의보혈", "받아주소서"]}  # blank lines dropped
    ]


def test_research_unscored_when_no_fragments(_runs, monkeypatch) -> None:
    """A song assembled before fragment persistence (or typed) has no fragments — the endpoint
    flags scored=False so the UI hides the meaningless 0% match and picks by preview instead."""
    store.save(_runs, _fake_run())  # _fake_run songs carry no "fragments" key

    def fake_scored(title, fragments, **kw):
        assert fragments == []  # nothing to score against
        return [app_module.lyrics_online.Candidate(song_id="111", title="보좌 앞으로", artist="")]

    monkeypatch.setattr(app_module.lyrics_online, "search_scored", fake_scored)
    r = client.post(f"/runs/{_runs}/research", json={"ref": "0", "title": "보좌 앞으로"})
    assert r.status_code == 200 and r.json()["scored"] is False and r.json()["candidates"]


def test_research_requires_title(_runs) -> None:
    store.save(_runs, _fake_run())
    assert client.post(f"/runs/{_runs}/research", json={"ref": "0", "title": " "}).status_code == 400


def test_research_unknown_ref_is_404(_runs) -> None:
    store.save(_runs, _fake_run())
    assert client.post(f"/runs/{_runs}/research", json={"ref": "9", "title": "x"}).status_code == 404


def test_research_network_error_returns_message(_runs, monkeypatch) -> None:
    """A gasazip hiccup surfaces as a message the phone shows, not a 500."""
    import httpx

    store.save(_runs, _fake_run())

    def boom(*a, **kw):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(app_module.lyrics_online, "search_scored", boom)
    r = client.post(f"/runs/{_runs}/research", json={"ref": "0", "title": "보좌 앞으로"})
    assert r.status_code == 200 and r.json()["candidates"] == [] and r.json()["error"]


def test_research_apply_rebreaks_chosen_lyrics(_runs, monkeypatch) -> None:
    """POST /research/apply fetches the picked candidate and rebreaks it like assemble does."""
    monkeypatch.setattr(app_module.lyrics_online, "fetch_lyrics", lambda sid: ["가사 한 줄", "두 줄"])
    monkeypatch.setattr(app_module.linebreak, "rebreak", lambda lines: lines + ["(rebroken)"])
    r = client.post(f"/runs/{_runs}/research/apply",
                    json={"song_id": "111", "title": "보좌 앞으로", "artist": "찬미워십"})
    assert r.status_code == 200
    # no repetition in the text -> no section suggestion (#206), operator labels manually
    assert r.json() == {"lines": ["가사 한 줄", "두 줄", "(rebroken)"], "sections": [], "arrangement": ""}


def test_research_apply_suggests_sections(_runs, monkeypatch) -> None:
    """POST /research/apply pre-labels section cards from the new canonical text (#206)."""
    verse = ["첫 소절 가사", "둘째 소절 가사"]
    chorus = ["후렴 가사 하나", "후렴 가사 둘"]
    monkeypatch.setattr(
        app_module.lyrics_online, "fetch_lyrics",
        lambda sid: verse + chorus + verse + chorus + chorus,
    )
    monkeypatch.setattr(app_module.linebreak, "rebreak", lambda lines: lines)
    r = client.post(f"/runs/{_runs}/research/apply",
                    json={"song_id": "111", "title": "아무 노래", "artist": "아무 밴드"})
    assert r.status_code == 200
    body = r.json()
    assert body["sections"] == [{"label": "V1", "lines": verse}, {"label": "C", "lines": chorus}]
    assert body["arrangement"] == "V1 C V1 C C"
    # lines are the deduped flattened mirror of the cards, matching the assemble path
    assert body["lines"] == verse + [""] + chorus
