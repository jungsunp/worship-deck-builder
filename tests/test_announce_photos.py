"""교회소식 photo collage: shrinking, layout, upload endpoints, and the Keynote build step."""

from __future__ import annotations

import io
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from worship_deck import photos, store
from worship_deck.keynote import build as B
from worship_deck.parse import ServiceData
from worship_deck.web import app as app_module
from worship_deck.web.app import app

client = TestClient(app)


def _jpeg(w: int, h: int, *, color=(200, 30, 30), exif_orientation: int | None = None) -> bytes:
    img = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    if exif_orientation:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        img.save(buf, "JPEG", exif=exif)
    else:
        img.save(buf, "JPEG")
    return buf.getvalue()


# ── photos.py ────────────────────────────────────────────────────────────────


def test_downscale_shrinks_long_edge_and_keeps_aspect(tmp_path) -> None:
    dest = tmp_path / "out.jpg"
    w, h = photos.downscale_photo(io.BytesIO(_jpeg(4000, 3000)), dest)
    assert (w, h) == (1920, 1440)
    with Image.open(dest) as im:
        assert im.size == (1920, 1440) and im.format == "JPEG"
    assert dest.stat().st_size < 400_000


def test_downscale_never_enlarges(tmp_path) -> None:
    assert photos.downscale_photo(io.BytesIO(_jpeg(800, 600)), tmp_path / "o.jpg") == (800, 600)


def test_downscale_bakes_in_exif_rotation(tmp_path) -> None:
    # Stored 400x300 with "rotate 90°" flag → displays as 300x400 portrait.
    raw = _jpeg(400, 300, exif_orientation=6)
    assert photos.downscale_photo(io.BytesIO(raw), tmp_path / "o.jpg") == (300, 400)


def test_downscale_rejects_non_images(tmp_path) -> None:
    with pytest.raises(ValueError):
        photos.downscale_photo(io.BytesIO(b"%PDF-1.4 not a photo"), tmp_path / "o.jpg")


def _ph(shape: str, n: int) -> list[dict]:
    w, h = (1920, 1440) if shape == "L" else (1440, 1920)
    return [{"w": w, "h": h, "i": i} for i in range(n)]


@pytest.mark.parametrize(
    "shape, n, sizes",
    [
        ("L", 0, []), ("L", 1, [1]), ("L", 6, [6]),   # six landscapes = the 10-04 slide
        ("L", 7, [4, 3]), ("L", 12, [6, 6]),
        ("P", 3, [3]), ("P", 4, [4]),
        ("P", 5, [3, 2]), ("P", 6, [3, 3]), ("P", 8, [4, 4]),  # not 6+2 or 8-up
    ],
)
def test_chunk_photos_keeps_photos_large_and_even(shape: str, n: int, sizes: list[int]) -> None:
    chunks = photos.chunk_photos(_ph(shape, n))
    assert [len(c) for c in chunks] == sizes
    assert [p["i"] for c in chunks for p in c] == list(range(n))  # order kept
    assert all(len(c) <= photos.MAX_PER_SLIDE for c in chunks)


MIXES = {
    "one portrait": [(3, 4)],
    "two landscape": [(4, 3)] * 2,
    "three mixed": [(3, 4), (4, 3), (3, 4)],
    "six landscape (10-04)": [(4, 3)] * 6,
    "six portrait": [(3, 4)] * 6,
    "five mixed (08-16)": [(3, 4), (4, 3), (4, 3), (3, 4), (4, 3)],
}


@pytest.mark.parametrize("name", MIXES)
def test_collage_layout_fits_slide_without_overlap_or_distortion(name: str) -> None:
    sizes = [(w * 100, h * 100) for w, h in MIXES[name]]
    boxes = photos.collage_layout(sizes)
    assert len(boxes) == len(sizes)
    for (x, y, w, h), (sw, sh) in zip(boxes, sizes):
        assert x >= 0 and y >= 0
        assert x + w <= photos.SLIDE_W and y + h <= photos.SLIDE_H
        assert abs(w / h - sw / sh) < 0.01  # aspect preserved (Keynote locks it)
    for i, a in enumerate(boxes):
        for b in boxes[i + 1 :]:
            apart = (
                a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0] or a[1] + a[3] <= b[1] or b[1] + b[3] <= a[1]
            )
            assert apart, f"{a} overlaps {b}"


def test_collage_layout_photos_stay_large_for_elders() -> None:
    boxes = photos.collage_layout([(4000, 3000)] * 6)  # the 10-04 case
    assert min(w for _, _, w, _ in boxes) >= 560  # operator's hand layout used ~640 px wide
    boxes = photos.collage_layout([(3000, 4000)] * 3)
    assert min(h for _, _, _, h in boxes) >= 800  # a row of three portraits stays tall


# ── upload endpoints ─────────────────────────────────────────────────────────

DATE = "2026-11-08"


@pytest.fixture()
def run_env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(app_module, "HYMN_DIR", tmp_path / "runs")
    store.save(DATE, ServiceData(date=DATE, announcements=["1. 하나", "2. 둘", "3. 셋"]))
    return tmp_path


def _post(*sizes: tuple[int, int], date: str = DATE):
    files = [("files", (f"KakaoTalk_{i}.jpeg", _jpeg(w, h), "image/jpeg")) for i, (w, h) in enumerate(sizes)]
    return client.post(f"/runs/{date}/photos", files=files)


def test_upload_shrinks_stores_and_lists(run_env) -> None:
    r = _post((4000, 3000), (3000, 4000))
    assert r.status_code == 200
    body = r.json()
    assert [(p["w"], p["h"]) for p in body["photos"]] == [(1920, 1440), (1440, 1920)]
    for p in body["photos"]:
        assert Path(p["path"]).is_file()
        assert str(run_env) in p["path"] and "/announce/" in p["path"]
    assert [p["path"] for p in store.load(DATE).announcement_photos] == [p["path"] for p in body["photos"]]


def test_upload_never_uses_client_filename(run_env) -> None:
    files = [("files", ("../../evil.jpg", _jpeg(100, 100), "image/jpeg"))]
    r = client.post(f"/runs/{DATE}/photos", files=files)
    assert r.status_code == 200
    name = Path(r.json()["photos"][0]["path"]).name
    assert name.startswith("photo-") and "evil" not in name


def test_upload_rejects_non_image_and_leaves_nothing(run_env) -> None:
    files = [
        ("files", ("ok.jpg", _jpeg(100, 100), "image/jpeg")),
        ("files", ("fake.jpg", b"not an image", "image/jpeg")),
    ]
    r = client.post(f"/runs/{DATE}/photos", files=files)
    assert r.status_code == 400
    assert store.load(DATE).announcement_photos == []
    assert not list((run_env / "runs" / DATE / "announce").iterdir())  # first one rolled back


def test_upload_enforces_count_and_size_limits(run_env, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "_MAX_PHOTOS", 2)
    assert _post((100, 100), (100, 100)).status_code == 200
    assert _post((100, 100)).status_code == 400  # a third would exceed the cap
    monkeypatch.setattr(app_module, "_MAX_PHOTOS", 18)
    monkeypatch.setattr(app_module, "_MAX_PHOTO_BYTES", 10)
    assert _post((100, 100)).status_code == 400


def test_upload_needs_an_existing_run(run_env) -> None:
    assert _post((100, 100), date="2026-01-01").status_code == 404
    assert client.post("/runs/not-a-date/photos", files=[("files", ("a.jpg", b"x", "image/jpeg"))]).status_code == 400


def test_serve_photo_and_path_guard(run_env) -> None:
    p = _post((200, 100)).json()["photos"][0]
    name = Path(p["path"]).name
    assert client.get(f"/runs/{DATE}/photos/{name}").status_code == 200
    assert client.get(f"/runs/{DATE}/photos/nope.jpg").status_code == 404
    assert client.get(f"/runs/{DATE}/photos/..%2F..%2Fx").status_code in (400, 404)


def test_reorder_and_delete(run_env) -> None:
    ps = _post((100, 100), (200, 100), (100, 200)).json()["photos"]
    names = [Path(p["path"]).name for p in ps]
    r = client.put(f"/runs/{DATE}/photos/order", json={"order": names[::-1]})
    assert [Path(p["path"]).name for p in r.json()["photos"]] == names[::-1]
    assert client.put(f"/runs/{DATE}/photos/order", json={"order": names[:2]}).status_code == 400
    r = client.delete(f"/runs/{DATE}/photos/{names[0]}")
    assert [Path(p["path"]).name for p in r.json()["photos"]] == names[:0:-1]
    assert not Path(ps[0]["path"]).exists()
    assert client.delete(f"/runs/{DATE}/photos/{names[0]}").status_code == 404


def test_put_run_keeps_server_owned_photo_list_but_saves_placement(run_env) -> None:
    photos_ = _post((100, 100)).json()["photos"]
    stale = asdict_run(store.load(DATE))
    stale["announcement_photos"] = []  # a page that loaded before the upload
    stale["announcement_photos_after"] = 2
    assert client.put(f"/runs/{DATE}", json=stale).status_code == 200
    saved = store.load(DATE)
    assert saved.announcement_photos == photos_
    assert saved.announcement_photos_after == 2


def asdict_run(d: ServiceData) -> dict:
    from dataclasses import asdict

    return asdict(d)


def test_review_page_has_photo_upload_ui() -> None:
    body = client.get("/review/2026-11-08").text
    assert "renderAnnouncePhotos" in body and "/photos" in body and 'accept = \'image/*\'' in body


# ── Keynote build ────────────────────────────────────────────────────────────


def _photo(tmp_path: Path, i: int, w=1440, h=1080) -> dict:
    p = tmp_path / f"p{i}.jpg"
    p.write_bytes(_jpeg(w, h))
    return {"path": str(p), "w": w, "h": h}


def test_place_collage_passes_layout_positions_to_applescript(tmp_path, monkeypatch) -> None:
    seen: dict = {}
    monkeypatch.setattr(B, "_run_osascript", lambda script, *args: seen.update(script=script, args=args) or "ok")
    ps = [_photo(tmp_path, i) for i in range(2)]
    B.place_collage("deck.key", 42, ps)
    assert seen["script"] == B._PLACE_COLLAGE
    key, idx, *rest = seen["args"]
    assert (key, idx) == ("deck.key", "42") and len(rest) == 8  # 2 photos x (path, x, y, width)
    assert rest[0] == str(Path(ps[0]["path"]).absolute())
    boxes = photos.collage_layout([(1440, 1080)] * 2)
    assert [int(rest[1]), int(rest[2]), int(rest[3])] == list(boxes[0][:3])


def test_fill_announcement_photos_duplicates_item_slide_per_collage_slide(tmp_path, monkeypatch) -> None:
    calls: list = []
    monkeypatch.setattr(B, "duplicate_slide", lambda k, i, n: calls.append(("dup", i, n)))
    monkeypatch.setattr(B, "place_collage", lambda k, i, ps: calls.append(("place", i, len(ps))))
    ps = [_photo(tmp_path, i) for i in range(8)]

    assert B.fill_announcement_photos("k", 120, ps) == 2
    assert calls == [("dup", 120, 2), ("place", 121, 4), ("place", 122, 4)]


def test_fill_announcement_photos_nothing_to_add(tmp_path, monkeypatch) -> None:
    calls: list = []
    monkeypatch.setattr(B, "duplicate_slide", lambda *a: calls.append(a))
    monkeypatch.setattr(B, "place_collage", lambda *a: calls.append(a))
    assert B.fill_announcement_photos("k", 120, []) == 0
    missing = [{"path": str(tmp_path / "gone.jpg"), "w": 10, "h": 10}]
    assert B.fill_announcement_photos("k", 120, missing) == 0  # file vanished: skip, don't crash
    assert calls == []


def _stubbed_build(monkeypatch, data: ServiceData) -> list[tuple]:
    from test_keynote_build import _stub_fills

    calls = _stub_fills(monkeypatch)
    monkeypatch.setattr(B, "fill_announcement_photos", lambda *a: calls.append(("fill_announcement_photos", a, {})) or 1)
    B.build(data, "tpl.key", "out.key")
    return calls


def test_build_adds_collage_after_chosen_item(tmp_path, monkeypatch) -> None:
    from test_keynote_build import _full_run

    data = replace(
        _full_run(), announcement_photos=[_photo(tmp_path, 0)], announcement_photos_after=1
    )
    calls = _stubbed_build(monkeypatch, data)
    names = [c[0] for c in calls]
    assert names.index("fill_announcement_photos") == names.index("fill_announcement_slides") + 1
    photo_call = next(c for c in calls if c[0] == "fill_announcement_photos")
    assert photo_call[1][:2] == ("out.key", 117)  # announcements start (117) + item 1 - 1


def test_build_collage_defaults_to_after_last_item(tmp_path, monkeypatch) -> None:
    from test_keynote_build import _full_run

    data = replace(_full_run(), announcement_photos=[_photo(tmp_path, 0)])  # after = 0
    calls = _stubbed_build(monkeypatch, data)
    photo_call = next(c for c in calls if c[0] == "fill_announcement_photos")
    assert photo_call[1][1] == 117 + 2 - 1  # two announcements → after the last


def test_build_without_photos_adds_no_collage(monkeypatch) -> None:
    from test_keynote_build import _full_run

    calls = _stubbed_build(monkeypatch, _full_run())
    assert "fill_announcement_photos" not in [c[0] for c in calls]

