"""End-to-end orchestrator: inbox -> structured service data -> rendered slides -> draft deck.

Wiring for the weekly run. Each step lives in its own module so it can be built and
tested independently. Human review happens in the web app between `assemble` and `build`.
"""

from __future__ import annotations

from . import obs


def run(service_date: str, inbox_dir: str) -> str:
    """Build a draft deck for the given service date. Returns the draft .key path.

    Steps (to implement):
      1. parse.bulletin       -> worship order, announcements, Bible refs, sermon title
      2. lyrics.transcribe    -> ordered lyric lines from band/choir sheet images
      3. bible.verses         -> 개역한글 + ESV text for each reference
      4. (review in web app)  -> human confirms song order & line breaks
      5. render.render        -> PNG per slide from data + background templates
      6. keynote.build        -> fresh deck from template, place PNGs + downloaded hymn slides
    """
    logger = obs.configure_logging()
    with obs.run_record(service_date):
        logger.info("Starting deck build for %s (inbox=%s)", service_date, inbox_dir)
        raise NotImplementedError
