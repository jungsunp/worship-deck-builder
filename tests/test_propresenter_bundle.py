"""Unit tests for the ``.probundle`` writer (#236) — pure zip + protobuf, CI-safe."""

import zipfile
from pathlib import Path

import pytest

from worship_deck.propresenter import pb  # noqa: F401 -- puts pb/ on sys.path

# Bindings are generated (scripts/gen_proto.sh), not committed — skip if absent.
pytest.importorskip(
    "presentation_pb2", reason="run scripts/gen_proto.sh to generate protobuf bindings"
)

from worship_deck.parse import ServiceData
from worship_deck.propresenter import build, bundle, styles


def _deck(tmp_path: Path, *images: Path) -> Path:
    """A minimal presentation: one image cue per given file, plus one text cue."""
    pres = build.new_presentation("week")
    for image in images:
        build.add_cue(pres, build.new_slide("image", str(image)), image.stem)
    build.add_cue(pres, build.new_slide("section_divider", "봉 헌"), "봉 헌")
    out = tmp_path / "week.pro"
    build.serialize(pres, str(out))
    return out


def _png(path: Path) -> Path:
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + path.name.encode())
    return path


def test_media_paths_decodes_the_file_urls(tmp_path):
    """elements.image percent-encodes the URL; the zip entry name must be the raw path back."""
    image = _png(tmp_path / "hymn 283.png")  # the space is what forces the decode
    pres = build.load(str(_deck(tmp_path, image)))

    assert bundle.media_paths(pres) == [image]


def test_media_paths_dedupes_and_keeps_first_seen_order(tmp_path):
    a, b = _png(tmp_path / "a.png"), _png(tmp_path / "b.png")
    pres = build.load(str(_deck(tmp_path, a, b, a)))

    assert bundle.media_paths(pres) == [a, b]


def test_bundle_holds_the_media_by_absolute_path_and_the_pro_at_the_root(tmp_path):
    """The entry name is the join key ProPresenter rewrites media URLs by on import."""
    a, b = _png(tmp_path / "a.png"), _png(tmp_path / "b.png")
    pro = _deck(tmp_path, a, b)

    out = bundle.write_bundle(pro)

    assert out == pro.with_suffix(".probundle")
    with zipfile.ZipFile(out) as zf:  # must be a *valid* zip — ProPresenter's own is not
        assert zf.namelist() == [str(a), str(b), "week.pro"]
        assert all(i.compress_type == zipfile.ZIP_STORED for i in zf.infolist())
        assert zf.read(str(a)) == a.read_bytes()


def test_bundled_pro_still_loads_and_keeps_its_original_urls(tmp_path):
    """ProPresenter rewrites the URLs on import, so the packed .pro must be byte-identical."""
    image = _png(tmp_path / "a.png")
    pro = _deck(tmp_path, image)

    with zipfile.ZipFile(bundle.write_bundle(pro)) as zf:
        packed = zf.read("week.pro")
    assert packed == pro.read_bytes()

    extracted = tmp_path / "extracted.pro"
    extracted.write_bytes(packed)
    assert bundle.media_paths(build.load(str(extracted))) == [image]


def test_bundle_refuses_to_ship_missing_media(tmp_path):
    """A bundle silently short a hymn page is worse than a failed build — the operator would
    only find out on Sunday."""
    image = _png(tmp_path / "a.png")
    pro = _deck(tmp_path, image)
    image.unlink()

    with pytest.raises(FileNotFoundError, match="a.png"):
        bundle.write_bundle(pro)


def test_a_deck_with_no_media_still_bundles(tmp_path):
    pro = _deck(tmp_path)

    with zipfile.ZipFile(bundle.write_bundle(pro)) as zf:
        assert zf.namelist() == ["week.pro"]


def test_the_weekly_deck_bundles_its_shipped_artwork(tmp_path):
    """End to end over the real church assets build() places on the opening plates."""
    pro = tmp_path / "week.pro"
    build.build(ServiceData(date="2026-08-30"), str(pro))

    with zipfile.ZipFile(bundle.write_bundle(pro)) as zf:
        names = zf.namelist()

    assert names == [styles.LOGO, *styles.PRE_SERVICE_IMAGES, "week.pro"]
    assert all(n.startswith("/") for n in names[:-1])  # absolute, leading slash preserved
