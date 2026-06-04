"""Mobile review/trigger web app (FastAPI), reached from the phone over Tailscale.

Flow: see the week's auto-detected songs / announcements / verses, reorder songs and fix
lyric line breaks, then tap Generate. The app calls pipeline.run() on the Mac and returns
a PDF preview of the draft. This is the human-in-the-loop checkpoint.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from worship_deck import obs, parse, store
from worship_deck.bible import verses
from worship_deck.lyrics import match
from worship_deck.lyrics import transcribe as lyrics_transcribe

app = FastAPI(title="Worship Deck")

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}

# Per-run assemble status, keyed by ISO service date. In-memory is enough: a single-process
# uvicorn on the Mac drives the whole run (status is lost on restart, which is acceptable).
_STATUS: dict[str, dict] = {}

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
  #assemble { background: #16a34a; margin-top: 0.5rem; }
  #status { margin-top: 1rem; font-size: 1rem; white-space: pre-wrap; }
  h2 { font-size: 1.1rem; margin: 1.5rem 0 0.5rem; }
  #inbox { list-style: none; padding: 0; margin: 0; }
  #inbox li { display: flex; align-items: center; gap: 0.5rem; padding: 0.5rem 0;
              border-bottom: 1px solid #eee; font-size: 1rem; }
  #inbox .name { flex: 1; word-break: break-all; }
  #inbox .size { color: #888; font-size: 0.85rem; }
  #inbox .del { width: auto; flex: none; padding: 0.4rem 0.7rem; font-size: 1rem;
                background: #dc2626; }
</style>
</head>
<body>
<h1>주보 / 악보 업로드</h1>
<form method="post" action="/upload" enctype="multipart/form-data">
  <input type="file" name="files" multiple>
  <button type="submit">Upload to inbox</button>
</form>
<h2>Inbox</h2>
<ul id="inbox"></ul>
<button id="assemble" type="button" onclick="assemble()">Assemble inbox</button>
<div id="status"></div>
<script>
let _timer;
async function loadInbox() {
  const {files} = await (await fetch('/inbox')).json();
  const ul = document.getElementById('inbox');
  ul.innerHTML = files.length ? '' : '<li>(empty)</li>';
  for (const f of files) {
    const li = document.createElement('li');
    const name = document.createElement('span'); name.className = 'name'; name.textContent = f.name;
    const size = document.createElement('span'); size.className = 'size'; size.textContent = (f.size / 1024).toFixed(1) + ' KB';
    const btn = document.createElement('button'); btn.className = 'del'; btn.textContent = '✕';
    btn.onclick = () => del(f.name);
    li.append(name, size, btn);
    ul.appendChild(li);
  }
}
async function del(name) {
  await fetch('/inbox/' + encodeURIComponent(name), {method: 'DELETE'});
  loadInbox();
}
loadInbox();
async function assemble() {
  document.getElementById('status').textContent = 'Starting…';
  const r = await fetch('/assemble', {method: 'POST'});
  const body = await r.json();
  if (!r.ok) { document.getElementById('status').textContent = 'Error: ' + (body.detail || r.status); return; }
  poll(body.status_url, body.service_date);
}
function poll(url, date) {
  clearInterval(_timer);
  _timer = setInterval(async () => {
    const s = await (await fetch(url)).json();
    document.getElementById('status').textContent = date + ': ' + s.status + (s.step ? ' (' + s.step + ')' : '') + (s.error ? '\\n' + s.error : '');
    if (s.status === 'done' || s.status === 'error') clearInterval(_timer);
  }, 2000);
}
</script>
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


@app.get("/inbox")
def inbox() -> dict:
    """Current inbox contents (filename + size), so the operator can confirm/correct uploads."""
    if not INBOX_DIR.exists():
        return {"files": []}
    files = sorted(p for p in INBOX_DIR.iterdir() if p.is_file())
    return {"files": [{"name": p.name, "size": p.stat().st_size} for p in files]}


@app.delete("/inbox/{name}")
def delete_inbox_file(name: str) -> dict:
    """Remove one uploaded file, path-safe (same guard as /upload: name must have no path parts)."""
    if Path(name).name != name:
        raise HTTPException(status_code=400, detail="invalid filename")
    target = INBOX_DIR / name
    if not target.is_file():
        raise HTTPException(status_code=404, detail="not found")
    target.unlink()
    return {"deleted": name}


def _bulletin_path() -> Path | None:
    """First PDF in the inbox (the weekly bulletin), or None if none uploaded."""
    pdfs = sorted(p for p in INBOX_DIR.glob("*.pdf") if p.is_file())
    return pdfs[0] if pdfs else None


def _sheet_paths() -> list[Path]:
    """Band lead-sheet images in the inbox, in filename order (medley page order)."""
    return sorted(p for p in INBOX_DIR.iterdir() if p.suffix.lower() in _IMAGE_SUFFIXES)


def _assemble_async(service_date: str) -> None:
    """Run the long read-only steps (transcribe + verses) and update the run + status.

    FastAPI runs this in a threadpool after the response is sent. Failures are caught
    and recorded in `_STATUS` so the page reports them instead of the worker crashing.
    """
    logger = obs.configure_logging()
    try:
        data = store.load(service_date)

        _STATUS[service_date] = {"status": "running", "step": "transcribe", "error": None}
        songs = [s for img in _sheet_paths() for s in lyrics_transcribe.transcribe(str(img))]
        match.assign_worship_songs(data.worship_order, songs)

        _STATUS[service_date] = {"status": "running", "step": "verses", "error": None}
        for row in data.worship_order:
            if row.get("ref"):
                row["passage"] = verses.lookup(row["ref"])

        store.save(service_date, data)
        _STATUS[service_date] = {"status": "done", "step": None, "error": None}
        logger.info("Assembled run for %s (%d song(s))", service_date, len(songs))
    except Exception as e:  # noqa: BLE001 - surface to the page, don't crash the worker
        logger.exception("Assemble failed for %s", service_date)
        _STATUS[service_date] = {"status": "error", "step": None, "error": repr(e)}


@app.post("/assemble")
def assemble(background_tasks: BackgroundTasks) -> dict:
    """Parse the inbox bulletin (fast, sync) then kick off transcribe + verses async.

    Parsing runs in-request so a missing bulletin / undetectable date fails immediately
    and we can return the detected service date as the poll key.
    """
    pdf = _bulletin_path()
    if pdf is None:
        raise HTTPException(status_code=400, detail="no bulletin (PDF) in inbox")

    data = parse.parse(str(pdf))
    try:
        service_date = parse.to_iso_date(data.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="could not detect service date in bulletin")

    store.save(service_date, data)
    _STATUS[service_date] = {"status": "running", "step": "transcribe", "error": None}
    background_tasks.add_task(_assemble_async, service_date)
    return {"service_date": service_date, "status_url": f"/assemble/{service_date}/status"}


@app.get("/assemble/{service_date}/status")
def assemble_status(service_date: str) -> dict:
    try:
        store.path_for(service_date)  # validate the date shape
    except ValueError:
        raise HTTPException(status_code=400, detail="service_date must be YYYY-MM-DD")
    return _STATUS.get(service_date, {"status": "unknown"})


# TODO: routes for detected-content review, reorder, generate, preview.
