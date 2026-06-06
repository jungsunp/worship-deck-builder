"""Tests for worship_deck.web.app — health, upload endpoint, mobile page, assemble."""

from __future__ import annotations

from dataclasses import asdict

import pytest
from fastapi.testclient import TestClient

from worship_deck import store
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


def test_index_serves_upload_form() -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.text
    assert 'enctype="multipart/form-data"' in body
    assert 'type="file"' in body


def test_upload_lands_in_inbox(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    resp = client.post("/upload", files={"files": ("bulletin.pdf", b"%PDF-data", "application/pdf")})
    assert resp.status_code == 200
    saved = tmp_path / "bulletin.pdf"
    assert saved.read_bytes() == b"%PDF-data"


def test_upload_multiple_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    resp = client.post(
        "/upload",
        files=[
            ("files", ("bulletin.pdf", b"pdf", "application/pdf")),
            ("files", ("sheet.png", b"png", "image/png")),
        ],
    )
    assert resp.status_code == 200
    assert (tmp_path / "bulletin.pdf").read_bytes() == b"pdf"
    assert (tmp_path / "sheet.png").read_bytes() == b"png"


def test_upload_sanitizes_filename(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    resp = client.post("/upload", files={"files": ("../evil.pdf", b"x", "application/pdf")})
    assert resp.status_code == 200
    assert (tmp_path / "evil.pdf").read_bytes() == b"x"
    # nothing escaped the inbox dir
    assert not (tmp_path.parent / "evil.pdf").exists()


# ── /inbox ───────────────────────────────────────────────────────────────────────


def test_inbox_lists_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    (tmp_path / "bulletin.pdf").write_bytes(b"%PDF")
    (tmp_path / "sheet.png").write_bytes(b"pngdata")
    resp = client.get("/inbox")
    assert resp.status_code == 200
    assert resp.json() == {
        "files": [
            {"name": "bulletin.pdf", "size": 4},
            {"name": "sheet.png", "size": 7},
        ]
    }


def test_inbox_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path / "missing")
    assert client.get("/inbox").json() == {"files": []}


def test_delete_inbox_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    f = tmp_path / "bulletin.pdf"
    f.write_bytes(b"%PDF")
    resp = client.delete("/inbox/bulletin.pdf")
    assert resp.status_code == 200
    assert not f.exists()


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
    (tmp_path / "sheet.png").write_bytes(b"png")
    monkeypatch.setattr(app_module.parse, "parse", lambda _p: _fake_data())
    monkeypatch.setattr(
        app_module.verses, "lookup_verses",
        lambda ref: [Verse(number=1, korean="한글", english="english")],
    )
    monkeypatch.setattr(
        app_module.hymn, "fetch_hymn_slides",
        lambda number, work_dir, **kw: [work_dir / "slide-1.png", work_dir / "slide-2.png"],
    )


def test_assemble_populates_run(_assemble_env, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        app_module.lyrics_transcribe, "transcribe",
        lambda _p: [Song(title="주 은혜임을", lines=["1절", "2절"])],
    )
    resp = client.post("/assemble")
    assert resp.status_code == 200
    date = resp.json()["service_date"]
    assert date == "2026-05-31"

    status = client.get(f"/assemble/{date}/status")
    assert status.json()["status"] == "done"

    data = store.load(date)
    assert data.worship_songs == [{"title": "주 은혜임을", "lines": ["1절", "2절"], "composer": ""}]
    assert data.call_to_worship_passage == [
        {"number": 1, "korean": "한글", "english": "english"},
    ]
    assert data.offering_hymn_images == [
        str(tmp_path / "runs" / date / "hymn" / "slide-1.png"),
        str(tmp_path / "runs" / date / "hymn" / "slide-2.png"),
    ]


def test_assemble_hymn_failure_is_nonfatal(_assemble_env, monkeypatch) -> None:
    monkeypatch.setattr(
        app_module.lyrics_transcribe, "transcribe",
        lambda _p: [Song(title="주 은혜임을", lines=["1절"])],
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
    def _boom(_p):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(app_module.lyrics_transcribe, "transcribe", _boom)
    resp = client.post("/assemble")
    assert resp.status_code == 200  # parse succeeded; the failure is in the async step
    date = resp.json()["service_date"]
    status = client.get(f"/assemble/{date}/status").json()
    assert status["status"] == "error"
    assert "ollama down" in status["error"]


def test_assemble_status_rejects_bad_date() -> None:
    assert client.get("/assemble/not-a-date/status").status_code == 400


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


def test_list_runs_newest_first(_runs) -> None:
    store.save("2026-05-31", _fake_run())
    store.save("2026-06-07", _fake_run())
    assert client.get("/runs").json() == {"runs": ["2026-06-07", "2026-05-31"]}


def test_list_runs_empty(_runs) -> None:
    assert client.get("/runs").json() == {"runs": []}


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


def test_put_run_400_bad_date() -> None:
    assert client.put("/runs/not-a-date", json={}).status_code == 400


def test_choir_paste_attaches_song(_runs) -> None:
    store.save(_runs, _fake_run())
    text = "주 하나님 지으신 모든 세계\n스튜어트 하인 작곡\n주 하나님 지으신 모든 세계"
    resp = client.post(f"/runs/{_runs}/choir", json={"text": text})
    assert resp.status_code == 200

    assert store.load(_runs).choir_song == {
        "title": "주 하나님 지으신 모든 세계",
        "lines": ["주 하나님 지으신 모든 세계"],
        "composer": "스튜어트 하인 작곡",
    }


def test_review_page_served() -> None:
    resp = client.get("/review/2026-05-31")
    assert resp.status_code == 200
    assert 'id="order"' in resp.text


def test_index_links_to_review() -> None:
    assert "/review/" in client.get("/").text
