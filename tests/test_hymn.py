"""Tests for worship_deck.hymn — offering-hymn PPT download + slide → PNG."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from worship_deck.hymn import download_hymn_ppt, fetch_hymn_slides

# ---------------------------------------------------------------------------
# download_hymn_ppt — mocked HTTP (two-step token flow)
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, *, json_data: dict | None = None, content: bytes = b"") -> None:
        self._json = json_data or {}
        self.content = content

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._json


def _fake_get_factory(calls: list[dict]):
    """Return a fake httpx.get: 1st call (action=token) -> token, 2nd -> pptx bytes."""

    def fake_get(url: str, **kw: object) -> _FakeResponse:
        params = kw.get("params", {})
        calls.append({"url": url, "params": params, "headers": kw.get("headers", {})})
        if params.get("action") == "token":
            return _FakeResponse(json_data={"token": "JWT123"})
        return _FakeResponse(content=b"PK\x03\x04 fake pptx")

    return fake_get


def test_download_writes_pptx(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import httpx

    calls: list[dict] = []
    monkeypatch.setattr(httpx, "get", _fake_get_factory(calls))

    out = download_hymn_ppt("220", tmp_path)

    assert out == tmp_path / "hymn-220.pptx"
    assert out.read_bytes() == b"PK\x03\x04 fake pptx"


def test_download_sends_token_request_then_file_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import httpx

    calls: list[dict] = []
    monkeypatch.setattr(httpx, "get", _fake_get_factory(calls))

    download_hymn_ppt("220", tmp_path, design="no-bg")

    assert len(calls) == 2
    token_call, file_call = calls
    # Step 1: token request carries type/design/number.
    assert token_call["params"] == {
        "action": "token",
        "type": "hymn",
        "design": "no-bg",
        "number": "220",
    }
    # Step 2: file request uses the issued token.
    assert file_call["params"] == {"token": "JWT123"}
    # A browser User-Agent is required on every request (header-less -> 403).
    for call in calls:
        assert "Mozilla/5.0" in call["headers"]["User-Agent"]


def test_download_raises_when_no_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import httpx

    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(json_data={}))

    with pytest.raises(RuntimeError, match="no download token"):
        download_hymn_ppt("220", tmp_path)


def test_http_error_propagates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import httpx

    class _ErrorResponse:
        def raise_for_status(self) -> None:
            raise httpx.HTTPStatusError("403", request=None, response=None)  # type: ignore[arg-type]

        def json(self) -> dict:
            return {}

    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _ErrorResponse())

    with pytest.raises(httpx.HTTPStatusError):
        download_hymn_ppt("220", tmp_path)


# ---------------------------------------------------------------------------
# Live integration test — needs network + LibreOffice + poppler; skipped in CI
# ---------------------------------------------------------------------------

@pytest.mark.local_only
def test_fetch_hymn_slides_live(tmp_path: Path) -> None:
    if shutil.which("soffice") is None or shutil.which("pdftoppm") is None:
        pytest.skip("soffice (LibreOffice) and/or pdftoppm (poppler) not installed")

    pngs = fetch_hymn_slides("220", tmp_path)

    # Hymn 220 came as a 9-slide PPT (verified in spike #50).
    assert len(pngs) == 9
    pages = [int(p.stem.split("-")[-1]) for p in pngs]
    assert pages == sorted(pages)  # numerically ordered
    for p in pngs:
        assert p.suffix == ".png"
        assert p.stat().st_size > 0
