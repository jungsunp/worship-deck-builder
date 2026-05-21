"""Mobile review/trigger web app (FastAPI), reached from the phone over Tailscale.

Flow: see the week's auto-detected songs / announcements / verses, reorder songs and fix
lyric line breaks, then tap Generate. The app calls pipeline.run() on the Mac and returns
a PDF preview of the draft. This is the human-in-the-loop checkpoint.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="NPC Worship Deck")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# TODO: routes for upload, detected-content review, reorder, generate, preview.
