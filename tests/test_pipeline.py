import json
import logging

import pytest

from worship_deck import obs, pipeline


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
    assert rec["ok"] is False
    assert "FileNotFoundError" in rec["error"]
