import json
import logging

import pytest

from worship_deck import obs, pipeline


def test_run_writes_log_and_run_record(tmp_path, monkeypatch):
    monkeypatch.setattr(obs, "LOG_DIR", tmp_path)
    logging.getLogger("worship_deck").handlers.clear()  # force re-config at tmp LOG_DIR

    with pytest.raises(NotImplementedError):
        pipeline.run("2026-05-31", str(tmp_path / "inbox"))

    assert (tmp_path / "worship_deck.log").exists()
    runs = (tmp_path / "runs.jsonl").read_text().splitlines()
    assert len(runs) == 1
    rec = json.loads(runs[0])
    assert rec["service_date"] == "2026-05-31"
    assert rec["ok"] is False
    assert "NotImplementedError" in rec["error"]
