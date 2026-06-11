"""Mobile review/trigger web app (FastAPI), reached from the phone over Tailscale.

Flow: see the week's auto-detected songs / announcements / verses, reorder songs and fix
lyric line breaks, then tap Generate. The app calls pipeline.run() on the Mac and returns
a PDF preview of the draft. This is the human-in-the-loop checkpoint.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import asdict, fields
from pathlib import Path

from fastapi import BackgroundTasks, Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from worship_deck import hymn, obs, parse, pipeline, store
from worship_deck.bible import verses
from worship_deck.lyrics import transcribe as lyrics_transcribe
from worship_deck.lyrics.choir import parse_choir_text
from worship_deck.parse import ServiceData

app = FastAPI(title="Worship Deck")

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}

# Parsed/transcribed fields that are also editable in the review UI. PUT /runs records which of
# these the operator changed (ServiceData.edited_fields) so a re-assemble preserves them (#105).
_EDITABLE_PARSED = (
    "worship_songs",
    "choir_song",
    "confession_song",
    "announcements",
    "offering_hymn_number",
    "offering_hymn_title",
)

# Human-readable labels for the re-assemble confirmation (#105): names exactly which sections a
# re-assemble will keep vs overwrite, so the operator can review before re-assembling.
_EDIT_LABELS = {
    "worship_songs": "찬양 songs (edited lyrics/order)",
    "choir_song": "성가대 choir lyrics (edited)",
    "confession_song": "고백의 찬양 lyrics (edited)",
    "announcements": "교회소식 announcements (edited)",
    "offering_hymn_number": "봉헌 hymn number (edited)",
    "offering_hymn_title": "봉헌 hymn title (edited)",
}
_REFRESH_LABELS = {
    "worship_songs": "찬양 songs (re-transcribed)",
    "choir_song": "성가대 choir lyrics (re-parsed from inbox text)",
    "confession_song": "고백의 찬양 lyrics (re-transcribed)",
    "announcements": "교회소식 announcements (re-parsed)",
    "offering_hymn_number": "봉헌 hymn number",
    "offering_hymn_title": "봉헌 hymn title",
}


def _kept_on_reassemble(existing: ServiceData) -> list[str]:
    """Labels for the review edits a re-assemble would preserve, for the confirm dialog (#105)."""
    kept: list[str] = []
    # Unedited choir/confession with no inbox input are carried over as-is (edited ones are
    # covered by _EDIT_LABELS below; with inbox input present they refresh instead).
    if (
        existing.choir_song.get("title")
        and "choir_song" not in existing.edited_fields
        and _choir_text() is None
    ):
        kept.append("성가대 choir lyrics")
    if (
        existing.confession_song.get("title")
        and "confession_song" not in existing.edited_fields
        and _confession_path() is None
    ):
        kept.append("고백의 찬양 lyrics")
    if existing.offering_hymn_verses:
        kept.append("봉헌 verse picks (" + ", ".join(str(v) for v in existing.offering_hymn_verses) + ")")
    if existing.sermon_extra_refs:
        kept.append("추가 말씀 구절 (" + ", ".join(existing.sermon_extra_refs) + ")")
    kept += [_EDIT_LABELS[f] for f in existing.edited_fields if f in _EDIT_LABELS]
    return kept


def _refreshed_on_reassemble(existing: ServiceData) -> list[str]:
    """Labels for the sections a re-assemble would overwrite from the bulletin (#105).

    The machine-only fields (verses, hymn images) always refresh when their input exists; the
    editable-parsed fields refresh only when the operator has NOT edited them.
    """
    refreshed: list[str] = []
    if existing.call_to_worship_ref or existing.sermon_ref:
        refreshed.append("Bible verses (예배의 부름 · 말씀)")
    if existing.offering_hymn_number:
        refreshed.append("봉헌 hymn slide images")
    for f in _EDITABLE_PARSED:
        if f in existing.edited_fields:
            continue
        if f.startswith("offering_hymn_") and not existing.offering_hymn_number:
            continue  # no 봉헌 this week — don't list hymn number/title
        if f == "choir_song" and _choir_text() is None:
            continue  # no inbox text — carried over, not refreshed
        if f == "confession_song" and _confession_path() is None:
            continue  # no inbox image — carried over, not refreshed
        refreshed.append(_REFRESH_LABELS[f])
    return refreshed

# Per-run assemble status, keyed by ISO service date. In-memory is enough: a single-process
# uvicorn on the Mac drives the whole run (status is lost on restart, which is acceptable).
_STATUS: dict[str, dict] = {}

# Per-run build status, keyed by ISO service date. Separate from _STATUS so a build doesn't
# clobber the assemble status the same date already carries.
_BUILD_STATUS: dict[str, dict] = {}

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
  input[type=file] { display: block; width: 100%; margin: 0.5rem 0; font-size: 1rem; }
  button { width: 100%; padding: 1rem; font-size: 1.1rem; border: 0;
           border-radius: 8px; background: #2563eb; color: #fff; }
  #assemble { background: #16a34a; margin-top: 0.5rem; }
  #status { margin-top: 1rem; font-size: 1rem; white-space: pre-wrap; }
  h2 { font-size: 1.1rem; margin: 1.5rem 0 0.5rem; }
  .slot { border: 1px solid #ddd; border-radius: 8px; padding: 0.75rem; margin: 0.5rem 0; }
  .slot .label { font-weight: 600; }
  .slot .hint { color: #888; font-size: 0.85rem; margin: 0.25rem 0; }
  .slot .count { color: #16a34a; font-size: 0.9rem; }
  .slot .none { color: #aaa; font-size: 0.9rem; margin: 0.25rem 0; }
  textarea { width: 100%; min-height: 6rem; font-size: 1rem; box-sizing: border-box; }
  .filerow { display: flex; align-items: center; gap: 0.5rem; padding: 0.4rem 0;
             font-size: 1rem; }
  .filerow .ok { color: #16a34a; font-weight: 700; flex: none; }
  .filerow .ok.warn { color: #d97706; }
  .filerow .name { flex: 1; word-break: break-all; }
  .filerow .size { color: #888; font-size: 0.85rem; flex: none; }
  .filerow .del { width: auto; flex: none; padding: 0.4rem 0.7rem; font-size: 1rem;
                  background: #dc2626; }
  #inbox { list-style: none; padding: 0; margin: 0; }
  #inbox li { border-bottom: 1px solid #eee; }
  #runs { list-style: none; padding: 0; margin: 0; }
  #runs li { padding: 0.5rem 0; border-bottom: 1px solid #eee; font-size: 1rem; }
  #runs a { color: #2563eb; text-decoration: none; }
</style>
</head>
<body>
<h1>주보 / 악보 업로드</h1>
<div class="slot">
  <div class="label">주보 (PDF)</div>
  <div class="files" id="files-bulletin"></div>
  <input type="file" accept=".pdf" onchange="uploadSlot(this, 'bulletin')">
</div>
<div class="slot">
  <div class="label">찬양 악보 (이미지) <span class="count" id="sheetCount"></span></div>
  <div class="hint">파일명 순서 = 메들리 순서</div>
  <div class="files" id="files-sheet"></div>
  <input type="file" multiple accept=".png,.jpg,.jpeg" onchange="uploadSlot(this, 'sheets')">
</div>
<div class="slot">
  <div class="label">고백의 찬양 악보 (이미지 1장)</div>
  <div class="files" id="files-confession"></div>
  <input type="file" accept=".png,.jpg,.jpeg" onchange="uploadSlot(this, 'confession')">
</div>
<div class="slot">
  <div class="label">성가대 가사 (텍스트)</div>
  <div class="hint">제목 / 작곡 줄 / 가사 — 절 사이 빈 줄 유지 · 자동 저장</div>
  <textarea id="choirText" oninput="choirChanged()" onblur="flushChoir()"></textarea>
  <div class="hint" id="choirStatus"></div>
</div>
<div id="otherWrap" hidden>
  <h2>기타 파일</h2>
  <div class="hint" style="color:#888;font-size:0.85rem">슬롯으로 인식되지 않아 빌드에 사용되지 않는
    파일 — 삭제 후 위 슬롯으로 다시 업로드</div>
  <ul id="inbox"></ul>
</div>
<button id="assemble" type="button" onclick="assemble()">Assemble inbox</button>
<div id="status"></div>
<h2>Review a run</h2>
<ul id="runs"></ul>
<script>
let _timer;
function fileRow(f, tag, mark) {
  const row = document.createElement(tag); row.className = 'filerow';
  const ok = document.createElement('span'); ok.className = mark ? 'ok warn' : 'ok';
  ok.textContent = mark || '✓';
  const name = document.createElement('span'); name.className = 'name'; name.textContent = f.name;
  const size = document.createElement('span'); size.className = 'size'; size.textContent = (f.size / 1024).toFixed(1) + ' KB';
  const btn = document.createElement('button'); btn.className = 'del'; btn.textContent = '✕';
  btn.onclick = () => del(f.name);
  row.append(ok, name, size, btn);
  return row;
}
async function loadInbox() {
  const {files, choir_text} = await (await fetch('/inbox')).json();
  const ta = document.getElementById('choirText');
  if (document.activeElement !== ta) ta.value = choir_text || '';
  for (const kind of ['bulletin', 'sheet', 'confession']) {
    const box = document.getElementById('files-' + kind);
    const mine = files.filter(f => f.kind === kind);
    box.innerHTML = mine.length ? '' : '<div class="none">아직 업로드 안 됨</div>';
    for (const f of mine) box.appendChild(fileRow(f, 'div'));
  }
  const sheets = files.filter(f => f.kind === 'sheet').length;
  document.getElementById('sheetCount').textContent = sheets ? '✓ ' + sheets + '장' : '';
  const others = files.filter(f => f.kind === 'other');
  document.getElementById('otherWrap').hidden = !others.length;
  const ul = document.getElementById('inbox');
  ul.innerHTML = '';
  for (const f of others) ul.appendChild(fileRow(f, 'li', '?'));
}
async function del(name) {
  await fetch('/inbox/' + encodeURIComponent(name), {method: 'DELETE'});
  loadInbox();
}
async function uploadSlot(input, kind) {
  if (!input.files.length) return;
  const fd = new FormData();
  for (const f of input.files) fd.append('files', f);
  const r = await fetch('/upload/' + kind, {method: 'POST', body: fd});
  const body = await r.json().catch(() => ({}));
  document.getElementById('status').textContent = r.ok
    ? 'Uploaded: ' + (body.saved || []).join(', ')
    : 'Upload error: ' + (body.detail || r.status);
  input.value = '';
  loadInbox();
}
let _choirTimer;
function choirChanged() {
  document.getElementById('choirStatus').textContent = '…';
  clearTimeout(_choirTimer);
  _choirTimer = setTimeout(saveChoir, 800);
}
function flushChoir() {
  if (!_choirTimer) return;
  clearTimeout(_choirTimer);
  saveChoir();
}
async function saveChoir() {
  _choirTimer = null;
  const text = document.getElementById('choirText').value;
  const r = await fetch('/inbox/choir', {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text}),
  });
  document.getElementById('choirStatus').textContent = r.ok
    ? (text.trim() ? '저장됨 ✓' : '비어 있음 — 저장 안 함') : '저장 오류: ' + r.status;
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
async function assemble(confirm) {
  document.getElementById('status').textContent = 'Starting…';
  const r = await fetch('/assemble' + (confirm ? '?confirm=1' : ''), {method: 'POST'});
  const body = await r.json();
  if (!r.ok) { document.getElementById('status').textContent = 'Error: ' + (body.detail || r.status); return; }
  if (body.needs_confirm) {
    const bullets = (items, empty) => items && items.length
      ? items.map(k => ' • ' + k).join('\\n') : ' • ' + empty;
    const msg = 'A run for ' + body.service_date + ' already exists. Re-assembling will:\\n\\n'
      + '↻ Refresh (overwrite from the bulletin):\\n'
      + bullets(body.refresh, '(nothing)') + '\\n\\n'
      + '✓ Keep (your review edits):\\n'
      + bullets(body.kept, '(none — no review edits saved yet)') + '\\n\\n'
      + 'Continue?';
    if (window.confirm(msg)) return assemble(true);
    document.getElementById('status').textContent = 'Cancelled.';
    return;
  }
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
  .hint { color: #888; font-size: 0.85rem; margin: 0.25rem 0 0.75rem; }
  .song { border-top: 1px solid #eee; margin-top: 0.5rem; padding-top: 0.5rem; }
  .song .hd { display: flex; align-items: center; gap: 0.5rem; }
  .song .hd .t, .song .t { flex: 1; font-weight: 500; }
  .song .hd button { width: auto; padding: 0.3rem 0.6rem; font-size: 1rem; }
  textarea, input { width: 100%; font-size: 1rem; box-sizing: border-box; }
  textarea { min-height: 5rem; } input { padding: 0.5rem; margin: 0.25rem 0; }
  .passage { white-space: pre-wrap; font-size: 0.95rem; }
  .hymngrid { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.5rem; }
  .hymnthumb { position: relative; width: 30%; cursor: pointer; border: 2px solid #16a34a;
               border-radius: 6px; overflow: hidden; }
  .hymnthumb img { display: block; width: 100%; }
  .hymnthumb.dropped { border-color: #ddd; opacity: 0.5; filter: grayscale(1); }
  .hymnthumb .badge { position: absolute; top: 0; right: 0; padding: 0.1rem 0.4rem;
                      font-size: 0.75rem; color: #fff; background: #16a34a; }
  .hymnthumb.dropped .badge { background: #999; }
  .hymncount { color: #888; font-size: 0.85rem; margin-top: 0.4rem; }
  button { padding: 0.8rem; font-size: 1.05rem; border: 0; border-radius: 8px;
           background: #2563eb; color: #fff; }
  #save { width: 100%; background: #16a34a; margin-top: 1rem; }
  #generate { width: 100%; background: #7c3aed; margin-top: 0.5rem; }
  #generate:disabled { background: #c4b5fd; }
  #status { margin-top: 0.75rem; font-size: 1rem; white-space: pre-wrap; }
  a { color: #2563eb; }
</style>
</head>
<body>
<a href="/">← Home</a>
<h1>Review <span id="date"></span></h1>
<p class="hint">전체 예배 순서대로 — 성가대 · 봉헌 · 광고는 해당 순서 자리에서 편집합니다.</p>
<div id="order"></div>

<button id="save" type="button" onclick="save()">Save</button>
<button id="generate" type="button" onclick="generate()">Generate deck</button>
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

// Identify which section a worship-order row carries, so its editor renders inline (mirrors
// the Python row predicates: the two 찬양 rows are told apart by the 성가대 leader/title).
const pk = row => (row.part || '').replace(/\\s/g, '');
const hasChoir = row => ((row.title || '') + (row.leader || '')).includes('성가대');
const isOpening = row => pk(row) === '찬양' && !hasChoir(row);
const isChoir = row => pk(row) === '찬양' && hasChoir(row);
const isConfession = row => pk(row) === '고백의찬양';
const isHymn = row => pk(row) === '봉헌';
const isAnnounce = row => pk(row) === '교회소식';
const isCtw = row => pk(row) === '예배의부름';
const isSermon = row => pk(row) === '말씀';

function render() {
  const order = document.getElementById('order');
  order.innerHTML = '';
  run.worship_order.forEach((row) => {
    const div = document.createElement('div'); div.className = 'row';
    const head = document.createElement('div');
    head.innerHTML = '<span class="part">' + (row.part || '') + '</span> '
      + '<span class="meta">' + [row.title, row.leader, row.ref].filter(Boolean).join(' · ') + '</span>';
    div.appendChild(head);
    if (isOpening(row)) renderMedley(div);
    else if (isChoir(row)) renderChoir(div);
    else if (isConfession(row)) renderConfession(div);
    else if (isHymn(row)) renderHymn(div);
    else if (isAnnounce(row)) renderAnnounce(div);
    else if (isCtw(row)) renderPassage(div, run.call_to_worship_passage);
    else if (isSermon(row)) renderSermon(div);
    order.appendChild(div);
  });
}

function renderMedley(div) {
  (run.worship_songs || []).forEach((song, s) => {
    const sd = document.createElement('div'); sd.className = 'song';
    const hd = document.createElement('div'); hd.className = 'hd';
    const t = document.createElement('span'); t.className = 't';
    t.textContent = song.title + (song.composer ? ' — ' + song.composer : '');
    const up = document.createElement('button'); up.textContent = '▲'; up.onclick = () => move(s, -1);
    const dn = document.createElement('button'); dn.textContent = '▼'; dn.onclick = () => move(s, 1);
    hd.append(t, up, dn); sd.appendChild(hd);
    const ta = document.createElement('textarea');
    ta.dataset.kind = 'worship'; ta.dataset.i = s; ta.value = (song.lines || []).join('\\n');
    sd.appendChild(ta);
    div.appendChild(sd);
  });
}

// Choir / confession lyrics arrive via the home-page inputs at assemble (#109); here the
// operator only edits them (spacing/typos). Interior blank lines are stanza breaks (#101).
function renderSong(div, song, kind, hint) {
  if (!song || !song.title) {
    const h = document.createElement('div'); h.className = 'hint'; h.textContent = hint;
    div.appendChild(h);
    return;
  }
  const sd = document.createElement('div'); sd.className = 'song';
  const t = document.createElement('div'); t.className = 't';
  t.textContent = song.title + (song.composer ? ' — ' + song.composer : '');
  sd.appendChild(t);
  const ta = document.createElement('textarea');
  ta.dataset.kind = kind; ta.value = (song.lines || []).join('\\n');
  sd.appendChild(ta);
  div.appendChild(sd);
}

function renderChoir(div) {
  renderSong(div, run.choir_song, 'choir', '성가대 가사 없음 — 홈 화면에서 가사를 입력하고 다시 Assemble');
}

function renderConfession(div) {
  renderSong(div, run.confession_song, 'confession', '고백의 찬양 가사 없음 — 홈 화면에서 악보를 업로드하고 다시 Assemble');
}

function mkInput(id, ph, val) {
  const i = document.createElement('input'); i.id = id; i.placeholder = ph; i.value = val || '';
  return i;
}

// Full ordered list of downloaded hymn PNG paths (kept + dropped); the grid renders from
// this while run.offering_hymn_images holds the kept subset the build will place (#84/#108).
let hymnAll = [];

function renderHymn(div) {
  div.appendChild(mkInput('hymnNumber', '찬송가 번호', run.offering_hymn_number));
  div.appendChild(mkInput('hymnTitle', '제목', run.offering_hymn_title));
  const grid = document.createElement('div'); grid.id = 'hymngrid'; grid.className = 'hymngrid';
  div.appendChild(grid);
  const count = document.createElement('div'); count.id = 'hymncount'; count.className = 'hymncount';
  div.appendChild(count);
  fetch('/runs/' + date + '/hymn').then(r => r.json()).then(j => {
    hymnAll = j.images || [];
    renderHymnGrid();
  });
}

function renderHymnGrid() {
  const grid = document.getElementById('hymngrid');
  if (!grid) return;
  grid.innerHTML = '';
  const kept = run.offering_hymn_images || [];
  hymnAll.forEach(path => {
    const on = kept.includes(path);
    const cell = document.createElement('div');
    cell.className = 'hymnthumb' + (on ? '' : ' dropped');
    cell.onclick = () => toggleHymn(path);
    const img = document.createElement('img');
    img.src = '/runs/' + date + '/hymn/' + path.split('/').pop();
    const badge = document.createElement('span'); badge.className = 'badge';
    badge.textContent = on ? '✓' : '제외';
    cell.append(img, badge);
    grid.appendChild(cell);
  });
  const c = document.getElementById('hymncount');
  if (c) c.textContent = '선택 ' + (run.offering_hymn_images || []).length + ' / ' + hymnAll.length + ' 슬라이드';
}

function toggleHymn(path) {
  const kept = run.offering_hymn_images || (run.offering_hymn_images = []);
  if (kept.includes(path)) run.offering_hymn_images = kept.filter(p => p !== path);
  else run.offering_hymn_images = hymnAll.filter(p => kept.includes(p) || p === path);  // keep slide order
  renderHymnGrid();
}

function renderAnnounce(div) {
  const ta = document.createElement('textarea');
  ta.id = 'announcements'; ta.dataset.kind = 'ann';
  ta.placeholder = '항목별 --- 로 구분 (첫 줄=제목, 나머지=내용)';
  ta.value = (run.announcements || []).join('\\n---\\n');
  div.appendChild(ta);
}

function renderPassage(div, passage) {
  if (!passage || !passage.length) return;
  const p = document.createElement('div'); p.className = 'passage';
  p.textContent = passage.map(v => v.number + '. ' + v.korean + ' / ' + v.english).join('\\n');
  div.appendChild(p);
}

// Main passage + the ad-hoc extra refs the pastor will cite (#114). Refs are looked up
// server-side on save, so the passage previews below reflect the LAST save, not unsaved edits.
function renderSermon(div) {
  renderPassage(div, run.sermon_passage);
  const ta = document.createElement('textarea');
  ta.dataset.kind = 'extrarefs';
  ta.placeholder = '추가 말씀 구절 — 한 줄에 하나 (예: 요 3:16, 시 4:15-20)';
  ta.value = (run.sermon_extra_refs || []).join('\\n');
  div.appendChild(ta);
  (run.sermon_extra_passages || []).forEach((p, i) => {
    const ref = (run.sermon_extra_refs || [])[i] || '';
    const h = document.createElement('div'); h.className = 'meta';
    h.textContent = ref + (p.length ? '' : ' — 조회 실패');
    div.appendChild(h);
    renderPassage(div, p);
  });
}

const splitLines = v => v.split('\\n').map(s => s.trim()).filter(Boolean);
// Keeps interior blank lines (stanza breaks, #101) — trims only leading/trailing ones.
const splitKeepBlanks = v => {
  const a = v.split('\\n').map(s => s.trim());
  while (a.length && !a[0]) a.shift();
  while (a.length && !a[a.length - 1]) a.pop();
  return a;
};

function syncFromDom() {
  document.querySelectorAll('#order textarea[data-kind="worship"]').forEach(ta => {
    run.worship_songs[ta.dataset.i].lines = splitLines(ta.value);
  });
  const choirTa = document.querySelector('#order textarea[data-kind="choir"]');
  if (choirTa && run.choir_song) run.choir_song.lines = splitKeepBlanks(choirTa.value);
  const confTa = document.querySelector('#order textarea[data-kind="confession"]');
  if (confTa && run.confession_song) run.confession_song.lines = splitKeepBlanks(confTa.value);
  const annTa = document.querySelector('#order textarea[data-kind="ann"]');
  if (annTa) run.announcements = annTa.value.split(/\\n-{3,}\\n/).map(s => s.trim()).filter(Boolean);
  const hn = document.getElementById('hymnNumber');
  if (hn) run.offering_hymn_number = hn.value.trim();
  const ht = document.getElementById('hymnTitle');
  if (ht) run.offering_hymn_title = ht.value.trim();
  const exTa = document.querySelector('#order textarea[data-kind="extrarefs"]');
  if (exTa) run.sermon_extra_refs = splitLines(exTa.value);
}

function move(s, d) {
  syncFromDom();
  const songs = run.worship_songs;
  const j = s + d;
  if (j < 0 || j >= songs.length) return;
  [songs[s], songs[j]] = [songs[j], songs[s]];
  render();
}

async function save() {
  syncFromDom();
  const r = await fetch('/runs/' + date, {
    method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(run),
  });
  if (!r.ok) { document.getElementById('status').textContent = 'Save error: ' + r.status; return false; }
  const body = await r.json();
  document.getElementById('status').textContent =
    'Saved.' + (body.warnings ? ' ' + body.warnings.join(' · ') : '');
  await load();  // re-render so freshly looked-up extra sermon verses preview (#114)
  return true;
}

let _buildTimer;
async function generate() {
  const btn = document.getElementById('generate');
  const st = document.getElementById('status');
  // Persist edits first — the build reads the saved run store, not the page.
  if (!(await save())) return;
  btn.disabled = true;
  st.textContent = 'Building deck… (this takes a minute on the Mac)';
  const r = await fetch('/runs/' + date + '/build', {method: 'POST'});
  const body = await r.json();
  if (!r.ok) { st.textContent = 'Build error: ' + (body.detail || r.status); btn.disabled = false; return; }
  clearInterval(_buildTimer);
  _buildTimer = setInterval(async () => {
    const s = await (await fetch(body.status_url)).json();
    if (s.status === 'running') return;
    clearInterval(_buildTimer);
    btn.disabled = false;
    if (s.status === 'done') st.textContent = 'Done — draft saved at ' + s.path + '\\nOpening in Keynote…';
    else st.textContent = 'Build failed: ' + (s.error || s.status);
  }, 2000);
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


# Each required source has a dedicated upload slot (#109); slot identity is the reserved
# inbox filename: bulletin.pdf, confession.<ext>, sheet-<origname>, choir.txt.
def _kind(name: str) -> str:
    if name == "bulletin.pdf":
        return "bulletin"
    if name.startswith("confession."):
        return "confession"
    if name.startswith("sheet-"):
        return "sheet"
    return "other"


@app.post("/upload/{kind}")
def upload(kind: str, files: list[UploadFile] = File(...)) -> dict:
    """Save uploads into the slot's reserved inbox name (#109).

    Single-file slots (bulletin, confession) replace the existing file; medley sheets keep
    their original (sanitized) names behind a constant prefix so filename order is preserved.
    Called by the home page's fetch-on-select JS, so it returns JSON, not a page.
    """
    if kind not in ("bulletin", "sheets", "confession"):
        raise HTTPException(status_code=400, detail="unknown upload slot")
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for f in files[: None if kind == "sheets" else 1]:
        name = Path(f.filename or "").name  # strip any path components (e.g. ../)
        if not name:
            continue
        suffix = Path(name).suffix.lower()
        if kind == "bulletin":
            if suffix != ".pdf":
                raise HTTPException(status_code=400, detail="bulletin must be a PDF")
            name = "bulletin.pdf"
        elif kind == "confession":
            if suffix not in _IMAGE_SUFFIXES:
                raise HTTPException(status_code=400, detail="confession sheet must be an image")
            for old in INBOX_DIR.glob("confession.*"):  # replace — extension may change
                old.unlink()
            name = f"confession{suffix}"
        else:
            if suffix not in _IMAGE_SUFFIXES:
                raise HTTPException(status_code=400, detail="sheets must be images")
            name = f"sheet-{name}"
        with (INBOX_DIR / name).open("wb") as out:
            shutil.copyfileobj(f.file, out)
        saved.append(name)
    return {"saved": saved}


@app.post("/inbox/choir")
def save_choir_text(body: dict = Body(...)) -> dict:
    """Write the 성가대 lyrics textarea into the inbox choir.txt (blank text clears it)."""
    text = body.get("text", "")
    target = INBOX_DIR / "choir.txt"
    if text.strip():
        INBOX_DIR.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return {"saved": True}
    if target.is_file():
        target.unlink()
    return {"saved": False}


@app.get("/inbox")
def inbox() -> dict:
    """Current inbox contents (filename + size + slot kind), plus the saved choir text.

    choir.txt is excluded from `files` — the home-page textarea is its UI.
    """
    if not INBOX_DIR.exists():
        return {"files": [], "choir_text": ""}
    files = sorted(p for p in INBOX_DIR.iterdir() if p.is_file() and p.name != "choir.txt")
    return {
        "files": [{"name": p.name, "size": p.stat().st_size, "kind": _kind(p.name)} for p in files],
        "choir_text": _choir_text() or "",
    }


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
    """The inbox bulletin PDF (fixed slot name), or None if none uploaded."""
    pdf = INBOX_DIR / "bulletin.pdf"
    return pdf if pdf.is_file() else None


def _sheet_paths() -> list[Path]:
    """Band lead-sheet images in the inbox, in filename order (medley page order)."""
    return sorted(p for p in INBOX_DIR.glob("sheet-*") if p.suffix.lower() in _IMAGE_SUFFIXES)


def _confession_path() -> Path | None:
    """The 고백의 찬양 sheet image in the inbox, or None if none uploaded."""
    imgs = sorted(p for p in INBOX_DIR.glob("confession.*") if p.suffix.lower() in _IMAGE_SUFFIXES)
    return imgs[0] if imgs else None


def _choir_text() -> str | None:
    """The saved 성가대 lyrics text from the inbox, or None if absent/blank."""
    target = INBOX_DIR / "choir.txt"
    if not target.is_file():
        return None
    text = target.read_text(encoding="utf-8")
    return text if text.strip() else None


def _assemble_async(service_date: str) -> None:
    """Run the long read-only steps (transcribe + verses) and update the run + status.

    FastAPI runs this in a threadpool after the response is sent. Failures are caught
    and recorded in `_STATUS` so the page reports them instead of the worker crashing.
    """
    logger = obs.configure_logging()
    try:
        data = store.load(service_date)
        warnings: list[str] = []  # missing-slot / best-effort failures; joined into the status

        _STATUS[service_date] = {"status": "running", "step": "transcribe", "error": None}
        # Skip re-transcription if the operator already hand-edited the medley (#105) — a
        # re-assemble must not clobber their line-break/order fixes.
        if "worship_songs" not in data.edited_fields:
            if not _sheet_paths():
                warnings.append("no 찬양 sheet images in inbox — medley not transcribed")
            songs = [s for img in _sheet_paths() for s in lyrics_transcribe.transcribe(str(img))]
            data.worship_songs = [asdict(s) for s in songs]

        # 고백의 찬양 (#109): transcribed from its dedicated sheet image. Best-effort like the
        # hymn below — a transcription hiccup must not discard the rest of the assemble.
        if "confession_song" not in data.edited_fields:
            img = _confession_path()
            if img is None:
                warnings.append("no 고백의 찬양 sheet image in inbox")
            else:
                try:
                    confession = lyrics_transcribe.transcribe(str(img))
                    if confession:
                        data.confession_song = asdict(confession[0])
                    else:
                        warnings.append("고백의 찬양 transcription found no lyrics")
                except Exception:  # noqa: BLE001 - best-effort, surface as a warning
                    logger.exception("고백의 찬양 transcription failed for %s", service_date)
                    warnings.append("고백의 찬양 transcription failed — edit it in review")

        # 성가대 (#109): parsed from the home-page choir text saved into the inbox.
        if "choir_song" not in data.edited_fields:
            text = _choir_text()
            if text is None:
                warnings.append("no 성가대 choir lyrics text in inbox")
            else:
                data.choir_song = asdict(parse_choir_text(text))

        _STATUS[service_date] = {"status": "running", "step": "verses", "error": None}
        if data.call_to_worship_ref:
            data.call_to_worship_passage = [asdict(v) for v in verses.lookup_verses(data.call_to_worship_ref)]
        if data.sermon_ref:
            data.sermon_passage = [asdict(v) for v in verses.lookup_verses(data.sermon_ref)]

        # Best-effort: a failed/forbidden hymn download must not discard the transcribe/verses
        # work above. On failure we record a warning and leave offering_hymn_images empty so
        # the operator can add the hymn manually.
        _STATUS[service_date] = {"status": "running", "step": "hymn", "error": None}
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
                warnings.append(f"hymn {data.offering_hymn_number} download failed — add it manually")

        store.save(service_date, data)
        _STATUS[service_date] = {
            "status": "done",
            "step": None,
            "error": None,
            "warning": "\n".join(warnings) or None,
        }
        logger.info("Assembled run for %s (%d song(s))", service_date, len(data.worship_songs))
    except Exception as e:  # noqa: BLE001 - surface to the page, don't crash the worker
        logger.exception("Assemble failed for %s", service_date)
        _STATUS[service_date] = {"status": "error", "step": None, "error": repr(e)}


@app.post("/assemble")
def assemble(background_tasks: BackgroundTasks, confirm: bool = False) -> dict:
    """Parse the inbox bulletin (fast, sync) then kick off transcribe + verses async.

    Parsing runs in-request so a missing bulletin / undetectable date fails immediately
    and we can return the detected service date as the poll key.

    Re-assembling a date that already has a run is destructive (#105): the fresh parse would
    wipe review edits. We warn first (return needs_confirm) unless `confirm`, then merge —
    preserving hymn verse picks, any operator-edited parsed fields, and carrying over
    choir/confession (refreshed from the inbox only when unedited and the input exists).
    """
    pdf = _bulletin_path()
    if pdf is None:
        raise HTTPException(status_code=400, detail="no bulletin (PDF) in inbox")

    data = parse.parse(str(pdf))
    try:
        service_date = parse.to_iso_date(data.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="could not detect service date in bulletin")

    existing = store.load(service_date) if store.exists(service_date) else None
    if existing is not None and not confirm:
        return {
            "service_date": service_date,
            "needs_confirm": True,
            "kept": _kept_on_reassemble(existing),
            "refresh": _refreshed_on_reassemble(existing),
        }
    if existing is not None:
        data.edited_fields = list(existing.edited_fields)
        # Carry over choir/confession as the baseline; _assemble_async refreshes them from the
        # inbox only when unedited and the inbox input exists.
        data.choir_song = existing.choir_song
        data.confession_song = existing.confession_song
        data.offering_hymn_verses = existing.offering_hymn_verses
        data.sermon_extra_refs = existing.sermon_extra_refs
        data.sermon_extra_passages = existing.sermon_extra_passages
        for f in existing.edited_fields:  # preserve operator-edited parsed fields
            setattr(data, f, getattr(existing, f))

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
    existing = store.load(service_date) if store.exists(service_date) else None
    data = ServiceData(**{k: v for k, v in body.items() if k in known})
    data.offering_hymn_verses = [int(v) for v in data.offering_hymn_verses]
    # Extra sermon refs (#114) are looked up on save, not at build: a typo'd ref fails here
    # with a visible warning instead of a minute into the Keynote build, and the review page
    # can preview the verses. Only changed refs hit the network; a failed lookup stores an
    # empty passage (build skips it) and the save still succeeds.
    warnings: list[str] = []
    # Operator-typed refs: trim, and collapse stray spaces around ':' and '-' ("시 4: 15-20" →
    # "시 4:15-20") so parse_ref accepts them and the slide label shows the clean form.
    data.sermon_extra_refs = [
        re.sub(r"\s*([:-])\s*", r"\1", r.strip()) for r in data.sermon_extra_refs if r.strip()
    ]
    if data.sermon_extra_refs != (existing.sermon_extra_refs if existing else []):
        data.sermon_extra_passages = []
        for ref in data.sermon_extra_refs:
            try:
                data.sermon_extra_passages.append([asdict(v) for v in verses.lookup_verses(ref)])
            except Exception:  # noqa: BLE001 - bad ref or lookup hiccup; keep the other edits
                data.sermon_extra_passages.append([])
                warnings.append(f"추가 말씀 구절 '{ref}' 조회 실패 — 확인 후 다시 저장")
    # Record which parsed/transcribed fields the operator actually changed, so a later
    # re-assemble preserves them instead of re-deriving them (#105). The pure-human fields
    # (offering_hymn_verses, sermon_extra_*) are always preserved, so they aren't tracked.
    edited = set(existing.edited_fields) if existing else set()
    if existing:
        edited |= {f for f in _EDITABLE_PARSED if getattr(data, f) != getattr(existing, f)}
    data.edited_fields = sorted(edited)
    store.save(service_date, data)
    return {"saved": service_date, "warnings": warnings} if warnings else {"saved": service_date}


@app.get("/runs/{service_date}/hymn")
def list_hymn_slides(service_date: str) -> dict:
    """List every downloaded 봉헌 hymn PNG (slide order) for the review grid (#84/#108).

    Paths match how _assemble_async stores them (str(HYMN_DIR/<date>/hymn/<name>)) so the
    client can membership-check them against the kept offering_hymn_images list.
    """
    try:
        store.path_for(service_date)  # validate the date shape
    except ValueError:
        raise HTTPException(status_code=400, detail="service_date must be YYYY-MM-DD")
    hymn_dir = HYMN_DIR / service_date / "hymn"
    if not hymn_dir.is_dir():
        return {"images": []}
    pngs = sorted(p for p in hymn_dir.iterdir() if p.suffix.lower() == ".png")
    return {"images": [str(p) for p in pngs]}


@app.get("/runs/{service_date}/hymn/{name}")
def get_hymn_slide(service_date: str, name: str) -> FileResponse:
    """Serve one hymn PNG for the review thumbnail grid, path-safe (mirrors /inbox guards)."""
    try:
        store.path_for(service_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="service_date must be YYYY-MM-DD")
    if Path(name).name != name:
        raise HTTPException(status_code=400, detail="invalid filename")
    target = HYMN_DIR / service_date / "hymn" / name
    if not target.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(target)


# ── Build (Generate) ─────────────────────────────────────────────────────────


def _build_async(service_date: str) -> None:
    """Drive Keynote to build the draft .key from the reviewed run, then open it on the Mac.

    FastAPI runs this in a threadpool after the response is sent. The build is slow
    (~60–90s, real Keynote) and local_only, so it must not block the phone's request.
    Failures are caught and recorded in `_BUILD_STATUS` so the page reports them.
    PDF preview is a follow-up (#26 split): for now the operator reviews the opened deck.
    """
    logger = obs.configure_logging()
    try:
        path = pipeline.run(service_date)
        # Open the draft in Keynote on the Mac (operator is at the machine). Best-effort:
        # the build already succeeded, so a failed `open` shouldn't flip the status to error.
        subprocess.run(["open", path], check=False)
        _BUILD_STATUS[service_date] = {"status": "done", "path": path, "error": None}
        logger.info("Built draft for %s at %s", service_date, path)
    except Exception as e:  # noqa: BLE001 - surface to the page, don't crash the worker
        logger.exception("Build failed for %s", service_date)
        _BUILD_STATUS[service_date] = {"status": "error", "path": None, "error": repr(e)}


@app.post("/runs/{service_date}/build")
def build_run(service_date: str, background_tasks: BackgroundTasks) -> dict:
    """Kick off the Keynote build for an assembled+reviewed run; poll the status_url for the path."""
    try:
        store.path_for(service_date)  # validate the date shape
    except ValueError:
        raise HTTPException(status_code=400, detail="service_date must be YYYY-MM-DD")
    if not store.exists(service_date):
        raise HTTPException(status_code=404, detail="no run for that date")
    _BUILD_STATUS[service_date] = {"status": "running", "path": None, "error": None}
    background_tasks.add_task(_build_async, service_date)
    return {"service_date": service_date, "status_url": f"/runs/{service_date}/build/status"}


@app.get("/runs/{service_date}/build/status")
def build_status(service_date: str) -> dict:
    try:
        store.path_for(service_date)  # validate the date shape
    except ValueError:
        raise HTTPException(status_code=400, detail="service_date must be YYYY-MM-DD")
    return _BUILD_STATUS.get(service_date, {"status": "unknown"})
