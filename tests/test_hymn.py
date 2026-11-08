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


# ---------------------------------------------------------------------------
# verse_labels — verse of each page from the PPTX's per-slide "verse dots" image
# ---------------------------------------------------------------------------

def _make_pptx(path: Path, dots: list[bytes | None]) -> Path:
    """A minimal PPTX: each slide has bg + body + (optional) dots media; None = 2-image slide."""
    import zipfile

    with zipfile.ZipFile(path, "w") as z:
        for i, d in enumerate(dots, 1):
            z.writestr(f"ppt/slides/slide{i}.xml", "<x/>")
            media = [f"image-{i}-1.png", f"image-{i}-2.png"] + ([f"image-{i}-3.png"] if d else [])
            rels = "".join(f'<Relationship Id="r{j}" Target="../media/{m}"/>' for j, m in enumerate(media))
            z.writestr(f"ppt/slides/_rels/slide{i}.xml.rels", f"<Relationships>{rels}</Relationships>")
            for m in media:
                z.writestr(f"ppt/media/{m}", d if m.endswith("-3.png") else f"{m}".encode())
    return path


def test_verse_labels_groups_pages_by_dots_image(tmp_path) -> None:
    from worship_deck.hymn import verse_labels

    pptx = _make_pptx(tmp_path / "h.pptx", [b"v1", b"v1", b"v2", b"v3", b"v3"])
    assert [(x["verse"], x["label"]) for x in verse_labels(pptx)] == [
        (1, "1절 (1/2)"), (1, "1절 (2/2)"), (2, "2절"), (3, "3절 (1/2)"), (3, "3절 (2/2)"),
    ]


def test_verse_labels_old_two_image_layout_is_unlabeled(tmp_path) -> None:
    from worship_deck.hymn import verse_labels

    assert verse_labels(_make_pptx(tmp_path / "h.pptx", [None, None])) == [None, None]
