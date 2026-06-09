# Gotchas & on-demand setup notes

Detailed, work-specific notes moved out of `CLAUDE.md` so they don't load into every
session's context. Read the relevant section before touching that area of the code.

## Keynote AppleScript gotchas

Drive Keynote via `osascript <file.applescript>`, mirroring `lyrics/transcribe.py`:

- `number & " "` builds a *list* (`"1837, 533"`), not text — coerce each: `((x as integer) as text)`.
- `item 2 of (position of t)` builds an object specifier and errors (-1700/-1728); do `set p to position of t` first, then `item 2 of p`.
- A loop var captured as `a reference to t` won't resolve later — store stable `text item i of s` specifiers instead.
- Stale open docs cause -1712 timeouts / -1700 errors; run `osascript -e 'tell application "Keynote" to close every document saving no'` before probing.
- Setting whole `object text` preserves the box's base font and turns `\n` into paragraphs.
- Keynote exposes **no** autoshrink flag, effective (shrunk) font size, or content height via AppleScript — only fixed box `width`/`height`. Size text headlessly via geometry estimates.
- `make new image` must be created *inside* a `tell slide N of d` block (`make new image at end of images of s` errors -10000). Images **lock aspect ratio**: setting `width` then `height` does NOT stretch — the last dimension set wins and the other re-proportions. So you can't full-bleed *stretch*; do aspect-fill instead — set the one constraining dimension to cover the slide, read back the actual size, then center (`position {(W-finalW)/2, (H-finalH)/2}`; overflow past the edge is clipped on export). See `place_image.applescript`.
- Verify slide appearance by exporting to PNG and reading the image: `export d to (POSIX file folder) as slide images with properties {image format:PNG}` (dest folder must pre-exist; export-*after*-delete fails — delete+save alone is fine).
- To **diff two decks' text** (e.g. a build output vs an operator-edited deck), dump per-slide text headlessly: open each, loop slides, emit `object text of` each text item under a `###SLIDE n###` marker, then diff. Each slide carries stacked + off-canvas {0,0} duplicate boxes, so dedupe identical lines per slide. Note: a built draft in `data/drafts/draft-<date>.key` is often hand-edited by the operator before review, so the per-run `data/runs/<date>.json` is the authoritative record of what the pipeline actually produced — audit defects against the JSON, not the draft.

## Lyric transcription (Apple Vision OCR + Ollama)

Lyric transcription is a **free local hybrid** (no API key): Apple Vision OCR via `swift src/worship_deck/lyrics/ocr_ko.swift <img>` (needs Xcode Command Line Tools; groups observations by baseline into whole lines) → a local Ollama model reassembles syllables into lyric lines. Set up: `brew install ollama && ollama serve && ollama pull qwen3.5:27b`. Env: `OLLAMA_MODEL` (default `qwen3.5:27b`), `OLLAMA_HOST` (default `http://127.0.0.1:11434`). Model bake-off on real sheets: `qwen3.5:27b` won (best recall/cleanest); `exaone3.5:7.8b` is a strong lighter pick; `qwen2.5vl:7b` was worst (truncates dense sheets). Reassembly is model-agnostic and sends `think: false` (qwen3.5 is a thinking model; output falls back to the `thinking` field). Feeding the image directly to the Ollama *vision* model crashed its runner on a real sheet — running reassembly as a **text** task on the Vision OCR output is why it's reliable.

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
