"""Logging, run records, and failure notifications for this local tool.

Lightweight observability without server infrastructure:
  - logging:     console + rotating file under logs/ (git-ignored)
  - run records: one JSON line per weekly run in logs/runs.jsonl (timing, ok/fail)
  - notify():    push a message to your phone via ntfy.sh on failure (set NTFY_TOPIC)
"""

from __future__ import annotations

import json
import logging
import os
import time
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(os.environ.get("LOG_DIR", "logs"))


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("worship_deck")
    if logger.handlers:
        return logger
    logger.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    fileh = RotatingFileHandler(LOG_DIR / "worship_deck.log", maxBytes=1_000_000, backupCount=5)
    fileh.setFormatter(fmt)
    logger.addHandler(console)
    logger.addHandler(fileh)
    return logger


def notify(message: str, title: str = "Worship Deck") -> None:
    """Push a phone notification via ntfy.sh if NTFY_TOPIC is set; otherwise no-op."""
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        return
    import httpx

    httpx.post(
        f"https://ntfy.sh/{topic}",
        data=message.encode("utf-8"),
        headers={"Title": title},
        timeout=10,
    )


class StepTimer:
    """Collect per-step durations via context manager."""

    def __init__(self) -> None:
        self._steps: dict[str, float] = {}

    @contextmanager
    def step(self, name: str):  # type: ignore[override]
        t = time.monotonic()
        try:
            yield
        finally:
            self._steps[name] = round(time.monotonic() - t, 1)

    def to_dict(self) -> dict[str, float]:
        return dict(self._steps)


def write_run_record(
    service_date: str,
    phase: str,
    ok: bool,
    seconds: float,
    steps: dict[str, float] | None = None,
    error: str | None = None,
) -> None:
    """Append one JSON record to logs/runs.jsonl (called directly for assemble phase)."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    rec: dict = {"service_date": service_date, "phase": phase, "ok": ok, "seconds": seconds}
    if steps:
        rec["steps"] = steps
    if error:
        rec["error"] = error
    with (LOG_DIR / "runs.jsonl").open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


@contextmanager
def run_record(service_date: str, phase: str = "build"):
    """Time a weekly run, append a JSON record, and notify the phone on failure.

    Yields a StepTimer — the caller may use `timer.step("name")` to record sub-step
    durations; they are written into the record's `steps` field automatically.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    timer = StepTimer()
    ok = False
    error: str | None = None
    try:
        yield timer
        ok = True
    except Exception as e:  # noqa: BLE001 - record then re-raise
        error = repr(e)
        notify(f"Deck build FAILED for {service_date}: {e}")
        raise
    finally:
        write_run_record(
            service_date,
            phase,
            ok,
            round(time.monotonic() - start, 1),
            timer.to_dict() or None,
            error,
        )
