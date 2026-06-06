"""Mobile review/trigger web app (FastAPI), reached from the phone over Tailscale.

Flow: see the week's auto-detected songs / announcements / verses, reorder songs and fix
lyric line breaks, then tap Generate. The app calls pipeline.run() on the Mac and returns
a PDF preview of the draft. This is the human-in-the-loop checkpoint.
"""

from __future__ import annotations

import shutil
from dataclasses import asdict, fields
from pathlib import Path

from fastapi import BackgroundTasks, Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from worship_deck import hymn, obs, parse, store
from worship_deck.bible import verses
from worship_deck.lyrics import match
from worship_deck.lyrics import transcribe as lyrics_transcribe
from worship_deck.lyrics.choir import parse_choir_text
from worship_deck.parse import ServiceData

app = FastAPI(title="Worship Deck")

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}

# Per-run assemble status, keyed by ISO service date. In-memory is enough: a single-process
# uvicorn on the Mac drives the whole run (status is lost on restart, which is acceptable).
_STATUS: dict[str, dict] = {}

# Uploaded bulletin/sheet files land here — a fixed local dir under the git-ignored
# data/ tree (no env var: files arrive via the upload form, not an iCloud drop-folder).
# Tests monkeypatch this to a tmp dir.
INBOX_DIR = Path("data/inbox")

# Downloaded offering-hymn slide PNGs land under HYMN_DIR/<service_date>/hymn/ (git-ignored,
# alongside the run-store JSON). Tests monkeypatch this to a tmp dir.
HYMN_DIR = Path("data/runs")


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
  #runs { list-style: none; padding: 0; margin: 0; }
  #runs li { padding: 0.5rem 0; border-bottom: 1px solid #eee; font-size: 1rem; }
  #runs a { color: #2563eb; text-decoration: none; }
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
<h2>Review a run</h2>
<ul id="runs"></ul>
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
async function loadRuns() {
  const {runs} = await (await fetch('/runs')).json();
  const ul = document.getElementById('runs');
  ul.innerHTML = runs.length ? '' : '<li>(none yet — assemble a bulletin first)</li>';
  for (const d of runs) {
    const li = document.createElement('li');
    const a = document.createElement('a'); a.href = '/review/' + d; a.textContent = d + ' — Review →';
    li.appendChild(a);
    ul.appendChild(li);
  }
}
loadInbox();
loadRuns();
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
    const st = document.getElementById('status');
    st.textContent = date + ': ' + s.status + (s.step ? ' (' + s.step + ')' : '') + (s.error ? '\\n' + s.error : '') + (s.warning ? '\\n⚠ ' + s.warning : '');
    if (s.status === 'done') st.innerHTML += ' <a href="/review/' + date + '">Review →</a>';
    if (s.status === 'done' || s.status === 'error') clearInterval(_timer);
  }, 2000);
}
</script>
</body>
</html>
"""


_REVIEW_HTML = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Worship Deck — Review</title>
<style>
  body { font-family: -apple-system, sans-serif; margin: 0; padding: 1.5rem; }
  h1 { font-size: 1.3rem; } h2 { font-size: 1.1rem; margin: 1.5rem 0 0.5rem; }
  .row { border: 1px solid #ddd; border-radius: 8px; padding: 0.75rem; margin: 0.5rem 0; }
  .part { font-weight: 600; } .meta { color: #888; font-size: 0.85rem; }
  .song { border-top: 1px solid #eee; margin-top: 0.5rem; padding-top: 0.5rem; }
  .song .hd { display: flex; align-items: center; gap: 0.5rem; }
  .song .hd .t { flex: 1; } .song .hd button { width: auto; padding: 0.3rem 0.6rem; font-size: 1rem; }
  textarea, input { width: 100%; font-size: 1rem; box-sizing: border-box; }
  textarea { min-height: 5rem; } input { padding: 0.5rem; margin: 0.25rem 0; }
  .passage { white-space: pre-wrap; font-size: 0.95rem; }
  button { padding: 0.8rem; font-size: 1.05rem; border: 0; border-radius: 8px;
           background: #2563eb; color: #fff; }
  #save { width: 100%; background: #16a34a; margin-top: 1rem; }
  #status { margin-top: 0.75rem; font-size: 1rem; }
  a { color: #2563eb; }
</style>
</head>
<body>
<a href="/">← Home</a>
<h1>Review <span id="date"></span></h1>
<div id="order"></div>

<h2>성가대 (choir) lyrics</h2>
<textarea id="choir" placeholder="제목 / 작곡 줄 / 가사… 붙여넣기"></textarea>
<button id="parseChoir" type="button" onclick="attachChoir()">Parse &amp; attach</button>

<h2>봉헌 (offering hymn)</h2>
<input id="hymnNumber" placeholder="찬송가 번호">
<input id="hymnTitle" placeholder="제목">
<input id="hymnVerses" placeholder="절 (예: 1,3) — 비우면 전체">

<h2>광고 (announcements)</h2>
<textarea id="announcements" placeholder="한 줄에 하나씩"></textarea>

<button id="save" type="button" onclick="save()">Save</button>
<div id="status"></div>
<script>
const date = location.pathname.split('/').pop();
document.getElementById('date').textContent = date;
let run = null;

async function load() {
  const r = await fetch('/runs/' + date);
  if (!r.ok) { document.getElementById('status').textContent = 'Load error: ' + r.status; return; }
  run = await r.json();
  render();
}

function render() {
  const order = document.getElementById('order');
  order.innerHTML = '';
  run.worship_order.forEach((row, r) => {
    const div = document.createElement('div'); div.className = 'row';
    const head = document.createElement('div');
    head.innerHTML = '<span class="part">' + (row.part || '') + '</span> '
      + '<span class="meta">' + [row.title, row.leader, row.ref].filter(Boolean).join(' · ') + '</span>';
    div.appendChild(head);
    (row.songs || []).forEach((song, s) => {
      const sd = document.createElement('div'); sd.className = 'song';
      const hd = document.createElement('div'); hd.className = 'hd';
      const t = document.createElement('span'); t.className = 't';
      t.textContent = song.title + (song.composer ? ' — ' + song.composer : '');
      const up = document.createElement('button'); up.textContent = '▲'; up.onclick = () => move(r, s, -1);
      const dn = document.createElement('button'); dn.textContent = '▼'; dn.onclick = () => move(r, s, 1);
      hd.append(t, up, dn); sd.appendChild(hd);
      const ta = document.createElement('textarea');
      ta.dataset.row = r; ta.dataset.song = s; ta.value = (song.lines || []).join('\\n');
      sd.appendChild(ta);
      div.appendChild(sd);
    });
    if (row.passage && row.passage.length) {
      const p = document.createElement('div'); p.className = 'passage';
      p.textContent = row.passage.map(v => v.number + '. ' + v.korean + ' / ' + v.english).join('\\n');
      div.appendChild(p);
    }
    order.appendChild(div);
  });
  document.getElementById('hymnNumber').value = run.offering_hymn_number || '';
  document.getElementById('hymnTitle').value = run.offering_hymn_title || '';
  document.getElementById('hymnVerses').value = (run.offering_hymn_verses || []).join(',');
  document.getElementById('announcements').value = (run.announcements || []).join('\\n');
}

function syncFromDom() {
  document.querySelectorAll('#order textarea').forEach(ta => {
    const lines = ta.value.split('\\n').map(s => s.trim()).filter(Boolean);
    run.worship_order[ta.dataset.row].songs[ta.dataset.song].lines = lines;
  });
  run.offering_hymn_number = document.getElementById('hymnNumber').value.trim();
  run.offering_hymn_title = document.getElementById('hymnTitle').value.trim();
  run.offering_hymn_verses = document.getElementById('hymnVerses').value
    .split(',').map(s => parseInt(s.trim(), 10)).filter(n => !isNaN(n));
  run.announcements = document.getElementById('announcements').value
    .split('\\n').map(s => s.trim()).filter(Boolean);
}

function move(r, s, d) {
  syncFromDom();
  const songs = run.worship_order[r].songs;
  const j = s + d;
  if (j < 0 || j >= songs.length) return;
  [songs[s], songs[j]] = [songs[j], songs[s]];
  render();
}

async function attachChoir() {
  const text = document.getElementById('choir').value;
  const r = await fetch('/runs/' + date + '/choir', {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text}),
  });
  if (!r.ok) { document.getElementById('status').textContent = 'Choir error: ' + r.status; return; }
  run = await r.json(); render();
  document.getElementById('status').textContent = 'Choir attached.';
}

async function save() {
  syncFromDom();
  const r = await fetch('/runs/' + date, {
    method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(run),
  });
  document.getElementById('status').textContent = r.ok ? 'Saved.' : 'Save error: ' + r.status;
}

load();
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
                row["passage"] = verses.lookup_verses(row["ref"])

        # Best-effort: a failed/forbidden hymn download must not discard the transcribe/verses
        # work above. On failure we record a warning and leave offering_hymn_images empty so
        # the operator can add the hymn manually.
        _STATUS[service_date] = {"status": "running", "step": "hymn", "error": None}
        warning = None
        if data.offering_hymn_number:
            try:
                pngs = hymn.fetch_hymn_slides(
                    data.offering_hymn_number, HYMN_DIR / service_date / "hymn"
                )
                data.offering_hymn_images = [str(p) for p in pngs]
            except Exception:  # noqa: BLE001 - download is best-effort, surface as a warning
                logger.exception(
                    "Hymn fetch failed for %s (hymn %s)", service_date, data.offering_hymn_number
                )
                warning = f"hymn {data.offering_hymn_number} download failed — add it manually"

        store.save(service_date, data)
        _STATUS[service_date] = {"status": "done", "step": None, "error": None, "warning": warning}
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


# ── Review / edit the assembled run ───────────────────────────────────────────


@app.get("/review/{service_date}", response_class=HTMLResponse)
def review(service_date: str) -> str:
    return _REVIEW_HTML


@app.get("/runs")
def list_runs() -> dict:
    """Assembled runs by service date, newest first, for the home page to link to review."""
    if not store.RUNS_DIR.exists():
        return {"runs": []}
    return {"runs": sorted((p.stem for p in store.RUNS_DIR.glob("*.json")), reverse=True)}


@app.get("/runs/{service_date}")
def get_run(service_date: str) -> dict:
    """Return the assembled run JSON for the review page to render."""
    try:
        store.path_for(service_date)  # validate the date shape
    except ValueError:
        raise HTTPException(status_code=400, detail="service_date must be YYYY-MM-DD")
    try:
        return asdict(store.load(service_date))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="no run for that date")


@app.put("/runs/{service_date}")
def put_run(service_date: str, body: dict = Body(...)) -> dict:
    """Persist the operator's edits (full-object replace; the page round-trips the whole run)."""
    try:
        store.path_for(service_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="service_date must be YYYY-MM-DD")
    known = {f.name for f in fields(ServiceData)}
    data = ServiceData(**{k: v for k, v in body.items() if k in known})
    data.offering_hymn_verses = [int(v) for v in data.offering_hymn_verses]
    store.save(service_date, data)
    return {"saved": service_date}


@app.post("/runs/{service_date}/choir")
def attach_choir(service_date: str, body: dict = Body(...)) -> dict:
    """Parse pasted 성가대 lyrics and attach them to the choir 찬양 row; return the updated run."""
    try:
        store.path_for(service_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="service_date must be YYYY-MM-DD")
    try:
        data = store.load(service_date)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="no run for that date")
    song = parse_choir_text(body.get("text", ""))
    for row in data.worship_order:
        if match._is_choir_row(row):
            row["songs"] = [asdict(song)]
            store.save(service_date, data)
            return asdict(data)
    raise HTTPException(status_code=404, detail="no 성가대 choir row in this run")
