import json
import logging
import zipfile
from pathlib import Path

import pytest

from worship_deck import obs, pipeline, store
from worship_deck.parse import ServiceData


def test_run_writes_log_and_run_record(tmp_path, monkeypatch):
    monkeypatch.setattr(obs, "LOG_DIR", tmp_path)
    logging.getLogger("worship_deck").handlers.clear()  # force re-config at tmp LOG_DIR

    # No run has been assembled for this date, so the build fails fast at store.load — before any
    # Keynote call, keeping this CI-safe. The point is that obs still records the failed run.
    with pytest.raises(FileNotFoundError):
        pipeline.run("2026-05-31")

    assert (tmp_path / "worship_deck.log").exists()
    runs = (tmp_path / "runs.jsonl").read_text().splitlines()
    assert len(runs) == 1
    rec = json.loads(runs[0])
    assert rec["service_date"] == "2026-05-31"
    assert rec["phase"] == "build"
    assert rec["ok"] is False
    assert "FileNotFoundError" in rec["error"]
    assert rec["ts"]  # wall-clock timestamp lets the perf dashboard order week-to-week runs


def test_write_run_record_persists_phase_steps_and_timestamp(tmp_path, monkeypatch):
    monkeypatch.setattr(obs, "LOG_DIR", tmp_path)
    obs.write_run_record("2026-06-07", "assemble", True, 95.0, {"ocr": 10.0, "bible": 5.0})

    rec = json.loads((tmp_path / "runs.jsonl").read_text().splitlines()[0])
    assert rec["phase"] == "assemble"
    assert rec["ok"] is True
    assert rec["seconds"] == 95.0
    assert rec["steps"] == {"ocr": 10.0, "bible": 5.0}
    assert rec["ts"]


def test_run_rejects_an_unknown_target():
    with pytest.raises(ValueError, match="unknown build target"):
        pipeline.run("2026-05-31", "powerpoint")


def test_run_pro_writes_a_probundle_and_records_its_own_phase(tmp_path, monkeypatch):
    """The .pro target bundles the deck with its media and leaves no loose .pro behind (#180).

    Needs the generated protobuf bindings (scripts/gen_proto.sh), which CI does not have.
    """
    from worship_deck.propresenter import pb  # noqa: F401 -- puts pb/ on sys.path

    pytest.importorskip("presentation_pb2", reason="run scripts/gen_proto.sh")

    monkeypatch.setattr(obs, "LOG_DIR", tmp_path)
    logging.getLogger("worship_deck").handlers.clear()  # force re-config at tmp LOG_DIR
    monkeypatch.setattr(store, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(pipeline, "DRAFTS_DIR", tmp_path / "drafts")
    store.save("2026-05-31", ServiceData(date="2026-05-31", sermon_title="시험"))

    out = pipeline.run("2026-05-31", "pro")

    assert out.endswith("draft-2026-05-31.probundle")
    assert Path(out).is_file()
    # .probundle only: the bare .pro references media by absolute path, so it is not a
    # deliverable and would just be a second file for the operator to pick the wrong one of.
    assert not Path(out).with_suffix(".pro").exists()
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert "draft-2026-05-31.pro" in names  # at the archive root; the name is the deck's PP name
    assert all(n.startswith("/") for n in names if n != "draft-2026-05-31.pro")  # media, absolute

    rec = json.loads((tmp_path / "runs.jsonl").read_text().splitlines()[-1])
    assert rec["phase"] == "build_pro"  # its own trend: ~2s here vs ~90s for Keynote
    assert rec["ok"] is True
    assert rec["steps"]["serialize"] >= 0
