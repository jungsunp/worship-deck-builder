# Gotchas & on-demand setup notes

Detailed, work-specific notes moved out of `CLAUDE.md` so they don't load into every
session's context. Read the relevant section before touching that area of the code.

## Keynote AppleScript gotchas

Drive Keynote via `osascript <file.applescript>`, mirroring `lyrics/transcribe.py`:

- `number & " "` builds a *list* (`"1837, 533"`), not text — coerce each: `((x as integer) as text)`.
- `item 2 of (position of t)` builds an object specifier and errors (-1700/-1728); do `set p to position of t` first, then `item 2 of p`.
- A loop var captured as `a reference to t` won't resolve later — store stable `text item i of s` specifiers instead.
- Stale open docs cause -1712 timeouts / -1700 errors; run `osascript -e 'tell application "Keynote" to close every document saving no'` before probing.
- **Open once, save once (#117).** Opening/saving the ~30 MB `master.key` is the dominant cost, so a build does it ~twice, not ~55×: `build()` runs `_ensure_keynote_ready()` (closes every doc, polls the count to 0), `save_draft.applescript` opens the template, `save … in outPath` (writes a pristine draft copy), then **closes the template and reopens the draft** so the open `front document` is bound to the **draft**, not the template (#108 fix). Every mutating/reading primitive then targets that open `front document` — no per-call `open`/`save`/`close`. `finalize.applescript` does the single end-of-build save: a **plain in-place `save front document`** (NOT `save … in outPath`). Two reasons it must be plain: (1) the doc is already bound to the draft, so a plain save writes the draft, never `master.key`; (2) `save … in outPath` is an explicit save-to-path that leaves Keynote's autosave bookkeeping out of sync, so the next autosave on the still-open draft warns *"could not be autosaved — changed by another application"*. **History:** before the #108 close-and-reopen, `save … in outPath` did NOT rebind the open doc (it stayed bound to the template), so finalize was forced to pass the explicit path to avoid a bare save corrupting `master.key`; that constraint is gone now that the template is closed up front. Because the precondition forces zero open docs, `front document` is unambiguously the draft. Corollary for Mac-only tests/probes: read back via `front document` (the edits are in-memory until finalize), don't re-`open` the path — and don't `close` after reading or you'll discard unsaved edits.
- Setting whole `object text` preserves the box's base font and turns `\n` into paragraphs. To set the size too, do `set size of object text of t to N` **after** setting the text (#115); `size of object text` reads back the **nominal** size, never the rendered one.
- Keynote exposes **no** autoshrink flag, effective (shrunk) font size, or content height via AppleScript — only fixed box `width`/`height`. Size text headlessly via geometry estimates.
- Verse body boxes are **fixed-height shrink-on-overflow** boxes: `height` never changes no matter what text/size you set (verified on a master.key scratch copy, #115). So a box's nominal font can be far from what renders (sermon boxes carried 120/76pt nominal while rendering tiny), and `read_verse_boxes` heights are a true, content-independent budget. Overflowing text shrinks inside the box — it never spills over the labels below.
- `make new image` must be created *inside* a `tell slide N of d` block (`make new image at end of images of s` errors -10000). Images **lock aspect ratio**: setting `width` then `height` does NOT stretch — the last dimension set wins and the other re-proportions. So you can't full-bleed *stretch*; do aspect-fill instead — set the one constraining dimension to cover the slide, read back the actual size, then center (`position {(W-finalW)/2, (H-finalH)/2}`; overflow past the edge is clipped on export). See `place_image.applescript`.
- Verify slide appearance by exporting to PNG and reading the image: `export d to (POSIX file folder) as slide images with properties {image format:PNG}` (dest folder must pre-exist; export-*after*-delete fails — delete+save alone is fine).
- To **diff two decks' text** (e.g. a build output vs an operator-edited deck), dump per-slide text headlessly: open each, loop slides, emit `object text of` each text item under a `###SLIDE n###` marker, then diff. Each slide carries stacked + off-canvas {0,0} duplicate boxes, so dedupe identical lines per slide. Note: a built draft in `data/drafts/draft-<date>.key` is often hand-edited by the operator before review, so the per-run `data/runs/<date>.json` is the authoritative record of what the pipeline actually produced — audit defects against the JSON, not the draft.

## Lyric transcription (Apple Vision OCR + Ollama)

Lyric transcription is a **free local hybrid** (no API key): Apple Vision OCR via `swift src/worship_deck/lyrics/ocr_ko.swift <img>` (needs Xcode Command Line Tools; groups observations by baseline into whole lines) → a local Ollama model reassembles syllables into lyric lines. Set up: `brew install ollama && ollama serve && ollama pull qwen3.5:27b`. Env: `OLLAMA_MODEL` (default `qwen3.5:27b`), `OLLAMA_HOST` (default `http://127.0.0.1:11434`). Model bake-off on real sheets: `qwen3.5:27b` won (best recall/cleanest); `exaone3.5:7.8b` is a strong lighter pick; `qwen2.5vl:7b` was worst (truncates dense sheets). Reassembly is model-agnostic and sends `think: false` (qwen3.5 is a thinking model; output falls back to the `thinking` field). Feeding the image directly to the Ollama *vision* model crashed its runner on a real sheet — running reassembly as a **text** task on the Vision OCR output is why it's reliable.

### Online canonical lyrics (gasazip.com, #110)

Since #110 the Ollama path is the **fallback**: `transcribe()` first detects the sheet's title (tallest mostly-Hangul OCR line near the top — `ocr_ko.swift` prints `height<TAB>text` for this) and looks up canonical lyrics on gasazip.com (`lyrics/online.py`). Gotchas:

- The bulletin names the **band**, not the songs (e.g. 마라나타) — the sheet title is the only song identity. Don't build anything on "bulletin title → lyrics" for the 찬양 medley.
- gasazip needs a **browser User-Agent** (like bibletoppt). godpeople returns 403 to scrapers; CCLI's API is ~$1000/yr + NDA — both rejected during the #110 spike.
- Titles are ambiguous (59 songs named "마라나타"), so `lookup()` fetches the top 5 candidates and ranks by **Hangul-bigram containment** against the OCR fragments (threshold 0.5). Wrong-song false positives score near 0; the right song near 1.0 even with note-split syllables, because normalization strips everything but Hangul.
- Handwritten arrangement marks can OCR *taller* than the printed title and may contain Hangul ("드럼만 - ((83)"); the ≥50%-Hangul ratio filter rejects them. Continuation pages (no printed title — their tallest Hangul is a lyric line) are rejected by the 16-Hangul-char cap → no title → straight to the Ollama fallback. Misses fail safe: every network/parse/match failure returns `None` and the local path runs.
- Some song pages embed a "제목 - 가수" header as the first lyric line — stripped only when both title and artist appear in it (a bare title-only first line can be a real lyric).
- 2026-06-07 sheet eval: 3/5 pages matched canonical lyrics exactly (보좌 앞으로, 죄에서 자유를 얻게 함은, 세상 모든 민족이); 2/5 were continuation pages that fell back, with zero false positives.

## 봉헌 hymn slide conversion

봉헌 hymn slide conversion (`hymn.pptx_to_pngs`) shells out to two **system** binaries (no pip deps): LibreOffice `soffice` (pptx → pdf) and poppler `pdftoppm` (pdf → png). Set up: `brew install --cask libreoffice && brew install poppler`. Gated behind `local_only` + `shutil.which` skips, so CI never needs them. bibletoppt requires a browser `User-Agent` (header-less → HTTP 403); the token is a ~5-min JWT, so request it immediately before the file GET.

## PDF generation & parsing (pdfplumber / Playwright)

- Generating pdfplumber-readable Korean PDFs requires Playwright (`page.pdf()`); `fpdf2` with TTC fonts produces PDFs with 0 extractable chars.
- pdfplumber emits `Could not get FontBBox` log noise on Playwright-generated PDFs — suppress with `logging.disable(logging.WARNING)` around `pdfplumber.open()`.
- Real bulletins are **US Legal landscape** (14"×8.5" = 1008×612 pts). `sample_bulletin.pdf` matches this format; do not change the paper size.
- pdfplumber flattens multi-column PDFs: all text at the same Y level is merged into one extracted line (worship order rows appear alongside announcement text on the same line).
- Playwright landscape PDFs: `page-break-after: always` on a `.page` div at an exact page boundary inserts a blank trailing page — use a separate `.page-break` div between pages instead.

## Testing & env one-offs

- `source .env` fails (unquoted space in `INBOX_DIR`); load a single var with `export $(grep '^ESV_API_KEY=' .env | xargs)`.
- Mock `httpx.get` in tests with `monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse())` and a minimal `_FakeResponse` class (see `tests/test_esv.py`). No `respx` or `pytest-httpx` needed.
