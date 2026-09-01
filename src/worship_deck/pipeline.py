"""End-to-end orchestrator: inbox -> structured service data -> rendered slides -> draft deck.

Wiring for the weekly run. Each step lives in its own module so it can be built and
tested independently. Human review happens in the web app between `assemble` and `build`.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import obs, store
from .keynote import build as keynote_build

DRAFTS_DIR = Path("data/drafts")


def run(service_date: str, target: str = "keynote") -> str:
    """Build a draft deck from the reviewed run store; return the written path (#29, #180).

    The "build" phase of the two-phase, web-driven run: parse + transcribe + verses happen at
    assemble time and the operator's edits are persisted to the per-run store, so this step just
    loads the reviewed `ServiceData` and drives the chosen builder. `target` picks it:

    * `keynote` — drive Keynote from `master.key` to data/drafts/draft-<date>.key (the fallback
      that still runs the service; unchanged).
    * `pro` — serialize a ground-up ProPresenter deck and pack it with its media into
      data/drafts/draft-<date>.probundle, the single file the operator imports (#236).

    Wrapped in `obs.run_record` so timing/failures are logged and pushed to the phone; the `.pro`
    run records its own phase, since a ~2s serialize and a ~90s Keynote build share no trend.

    Raises:
        ValueError: on an unknown `target`.
        FileNotFoundError: if no run has been assembled for `service_date`.
        RuntimeError: if TEMPLATE_KEY is unset, or a Keynote script fails (not on a Mac, etc.).
    """
    if target not in ("keynote", "pro"):
        raise ValueError(f"unknown build target {target!r} — expected 'keynote' or 'pro'")
    logger = obs.configure_logging()
    with obs.run_record(service_date, phase="build" if target == "keynote" else "build_pro") as timer:
        logger.info("Starting %s deck build for %s", target, service_date)
        data = store.load(service_date)
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        # Absolute path: Keynote's `save ... in (POSIX file ...)` throws -609 on a relative path.
        out = str((DRAFTS_DIR / f"draft-{service_date}").resolve())

        if target == "pro":
            # Imported here, not at module scope: the propresenter package needs the generated
            # protobuf bindings (scripts/gen_proto.sh), which are git-ignored and absent on CI —
            # a top-level import would break every test that touches the pipeline or the web app.
            from .propresenter import build as pro_build
            from .propresenter import bundle

            pro = f"{out}.pro"
            _, build_steps = pro_build.build(data, pro)
            timer.merge(build_steps)
            # A bare .pro references its media by absolute path, so it only opens on this Mac.
            # The bundle is the deliverable; the loose .pro would only be a second file to
            # confuse the operator (and ProPresenter caches one it has already read).
            packed = bundle.write_bundle(pro)
            Path(pro).unlink()
            return str(packed)

        template = os.environ.get("TEMPLATE_KEY")
        if not template:
            raise RuntimeError("TEMPLATE_KEY is not set — point it at the master .key template.")
        path, build_steps = keynote_build.build(data, template, f"{out}.key")
        timer.merge(build_steps)
        return path
