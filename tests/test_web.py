"""Tests for worship_deck.web.app — health, upload endpoint, mobile page."""

from __future__ import annotations

from fastapi.testclient import TestClient

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
