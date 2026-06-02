"""Mobile review/trigger web app (FastAPI), reached from the phone over Tailscale.

Flow: see the week's auto-detected songs / announcements / verses, reorder songs and fix
lyric line breaks, then tap Generate. The app calls pipeline.run() on the Mac and returns
a PDF preview of the draft. This is the human-in-the-loop checkpoint.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse

app = FastAPI(title="Worship Deck")

# Uploaded bulletin/sheet files land here — a fixed local dir under the git-ignored
# data/ tree (no env var: files arrive via the upload form, not an iCloud drop-folder).
# Tests monkeypatch this to a tmp dir.
INBOX_DIR = Path("data/inbox")


_INDEX_HTML = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Worship Deck — Upload</title>
<style>
  body { font-family: -apple-system, sans-serif; margin: 0; padding: 1.5rem; }
  h1 { font-size: 1.3rem; }
  input[type=file] { display: block; width: 100%; margin: 1rem 0; font-size: 1rem; }
  button { width: 100%; padding: 1rem; font-size: 1.1rem; border: 0;
           border-radius: 8px; background: #2563eb; color: #fff; }
</style>
</head>
<body>
<h1>주보 / 악보 업로드</h1>
<form method="post" action="/upload" enctype="multipart/form-data">
  <input type="file" name="files" multiple>
  <button type="submit">Upload to inbox</button>
</form>
</body>
</html>
"""


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _INDEX_HTML


@app.post("/upload", response_class=HTMLResponse)
def upload(files: list[UploadFile] = File(...)) -> str:
    dest = INBOX_DIR
    dest.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for f in files:
        name = Path(f.filename or "").name  # strip any path components (e.g. ../)
        if not name:
            continue
        with (dest / name).open("wb") as out:
            shutil.copyfileobj(f.file, out)
        saved.append(name)
    items = "".join(f"<li>{n}</li>" for n in saved) or "<li>(none)</li>"
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<h1>Saved {len(saved)} file(s)</h1><ul>{items}</ul>"
        "<a href='/'>← Upload more</a>"
    )


# TODO: routes for detected-content review, reorder, generate, preview.
