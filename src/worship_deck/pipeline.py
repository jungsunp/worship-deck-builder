"""End-to-end orchestrator: inbox -> structured service data -> rendered slides -> draft deck.

Wiring for the weekly run. Each step lives in its own module so it can be built and
tested independently. Human review happens in the web app between `assemble` and `build`.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import obs, store
from .keynote import build as keynote_build


def run(service_date: str) -> str:
    """Build a draft deck from the reviewed run store. Returns the draft .key path (#29).

    The "build" phase of the two-phase, web-driven run: parse + transcribe + verses happen at
    assemble time and the operator's edits are persisted to the per-run store, so this step just
    loads the reviewed `ServiceData` and drives Keynote to produce data/drafts/draft-<date>.key.
    Wrapped in `obs.run_record` so timing/failures are logged and pushed to the phone.

    Raises:
        FileNotFoundError: if no run has been assembled for `service_date`.
        RuntimeError: if TEMPLATE_KEY is unset, or a Keynote script fails (not on a Mac, etc.).
    """
    logger = obs.configure_logging()
    with obs.run_record(service_date, phase="build") as timer:
        logger.info("Starting deck build for %s", service_date)
        data = store.load(service_date)
        template = os.environ.get("TEMPLATE_KEY")
        if not template:
            raise RuntimeError("TEMPLATE_KEY is not set — point it at the master .key template.")
        # Absolute path: Keynote's `save ... in (POSIX file ...)` throws -609 on a relative path.
        out = str(Path(f"data/drafts/draft-{service_date}.key").resolve())
        path, build_steps = keynote_build.build(data, template, out)
        timer._steps.update(build_steps)
        return path
