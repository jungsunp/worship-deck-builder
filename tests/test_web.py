"""Tests for worship_deck.web.app — health, upload endpoint, mobile page, assemble."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from worship_deck import store
from worship_deck.bible.verses import Passage
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


# ── /assemble ──────────────────────────────────────────────────────────────────
# The heavy steps (Vision OCR + Ollama, ESV) are monkeypatched so these run on CI.
# Starlette's TestClient runs the BackgroundTask before returning, so the assemble
# response already reflects the completed run — no real polling loop needed.


def _fake_data() -> ServiceData:
    """Parsed bulletin: an opening 찬양 row (band name) + a ref-bearing row."""
    return ServiceData(
        date="2026년 5월 31일",
        worship_order=[
            {"part": "찬양", "title": "마라나타", "leader": "", "ref": ""},
            {"part": "예배의 부름", "title": "", "leader": "", "ref": "시 133:1-3"},
        ],
    )


@pytest.fixture
def _assemble_env(tmp_path, monkeypatch):
    """Inbox + runs dir in tmp; parse/transcribe/lookup faked."""
    monkeypatch.setattr(app_module, "INBOX_DIR", tmp_path)
    monkeypatch.setattr(store, "RUNS_DIR", tmp_path / "runs")
    (tmp_path / "bulletin.pdf").write_bytes(b"%PDF")
    (tmp_path / "sheet.png").write_bytes(b"png")
    monkeypatch.setattr(app_module.parse, "parse", lambda _p: _fake_data())
    monkeypatch.setattr(
        app_module.verses, "lookup",
        lambda ref: Passage(reference=ref, korean="한글", english="english"),
    )


def test_assemble_populates_run(_assemble_env, monkeypatch) -> None:
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
    opening, ref_row = data.worship_order
    assert opening["songs"] == [{"title": "주 은혜임을", "lines": ["1절", "2절"], "composer": ""}]
    assert ref_row["passage"] == {
        "reference": "시 133:1-3", "korean": "한글", "english": "english",
    }


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
