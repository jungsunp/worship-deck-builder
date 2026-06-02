# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

Builds a weekly Keynote worship deck for a Korean church's Sunday worship services. The same deck is shared across all services (e.g. 9am and 11am). **Requires a Mac that is powered on and logged in** — Keynote automation needs the macOS window server. An iPhone reaches the FastAPI web app over Tailscale to review and trigger builds.

Per-section content sources (see `config/slide_map.yaml`):
- **Worship songs (찬양):** band **lead sheet** images shared via Kakao — often a multi-song medley with red arrangement marks (`V/C/B` sections, `×N` repeats, X-out skips, `→` segues). Only the **lyrics** are transcribed (the band runs the arrangement live from the sheets); a free local hybrid does it — Apple Vision OCR (`lyrics/ocr_ko.swift`) reads the Korean text, then a local Ollama model reassembles the note-split syllables into clean lines. No API/cloud.
- **Choir (성가대):** lyrics arrive as **raw text** (title + composer line + lyric lines), pasted into the review app — not an image.
- **Offering hymn (봉헌):** a 찬송가 hymn identified in the **bulletin** by number/title/verses; slides are **downloaded online** as a PowerPoint per song (not stored locally), converted to images, and placed as-is.

## Commands

```bash
pip install -e ".[dev]"
python -m playwright install chromium  # only for scripts/make_fixtures.py (sample-bulletin PDF)
cp .env.example .env

ruff check src tests
pytest -m "not local_only"   # CI-safe; no Mac/Keynote needed
pytest -m local_only          # Mac + Keynote required
set -a && source .env && set +a  # load .env vars before pytest (live tests need API keys)
uvicorn worship_deck.web.app:app --host 127.0.0.1 --port 8787 --reload
uvicorn worship_deck.web.app:app --host 0.0.0.0 --port 8787  # LAN/phone access: same Wi-Fi, hit http://<mac-lan-ip>:8787/ (needs macOS firewall "Allow"). Off-network access is via Tailscale (#28).
```

## Architecture

`pipeline.py` orchestrates five steps: bulletin PDF parse → local lyric transcription (Apple Vision OCR + Ollama reassembly) → Bible verse lookup → **human review in web app** → AppleScript Keynote build (duplicate section slides + set native text) → `data/drafts/draft-YYYY-MM-DD.key`.

**Key design:** the church builds slides as **native Keynote text boxes**, so the builder edits them in place rather than rendering images. Starting from the template deck (`templates/master.key`, a real recent deck), the AppleScript build step sets each slide's text runs and duplicates section slides to fit the week's content (lyrics/announcements expand). The **only image slides** are offering-hymn pages (downloaded online as a 찬송가 PowerPoint, converted to images), band lead sheets, and media (e.g. countdown video) — placed as-is. There is no HTML/PNG rendering step.

`obs.py` wraps the pipeline with rotating-file logging (`logs/`), a per-run JSONL record (`logs/runs.jsonl`), and optional phone push notifications via ntfy.sh (`NTFY_TOPIC`). All are git-ignored.

Section structure, content sources, and render modes are declared in `config/slide_map.yaml`.

Implementation status: `parse` (date extraction done, worship order TODO), `bible` (Korean ref parsing + ESV fetch done, verse assembly TODO), `lyrics` (transcription done — Vision+Ollama hybrid; `chunk()` into ≤2-line slides TODO, #18), `keynote` is a stub. `keynote.build` drives Keynote via AppleScript to duplicate slides and set native text. Implement remaining work in order: `parse` → `bible` → `lyrics` → `keynote`.

## Constraints

- `data/` is git-ignored. **Never commit it** — real bulletins contain member names and offering amounts.
- `tests/fixtures/` contains sanitized real bulletin data (member names/amounts scrubbed). Never commit unsanitized files. Regenerate with `python scripts/make_fixtures.py` (macOS only).
- `data/real-bulletin.pdf` and `data/real-sheet.png` — drop real files here for local testing. `TEMPLATE_KEY` env var points to the master Keynote template.
- `templates/master.key` is git-ignored (large, church media). Place locally, never commit.
- `local_only` marker gates any test needing macOS + Keynote or live API calls; CI runs on Ubuntu and skips them. Add `if not os.environ.get("KEY"): pytest.skip(...)` inside the test body too — the marker alone doesn't skip when running without `-m "not local_only"`.
- Lyric transcription is a **free local hybrid** (no API key): Apple Vision OCR via `swift src/worship_deck/lyrics/ocr_ko.swift <img>` (needs Xcode Command Line Tools; groups observations by baseline into whole lines) → a local Ollama model reassembles syllables into lyric lines. Set up: `brew install ollama && ollama serve && ollama pull qwen3.5:27b`. Env: `OLLAMA_MODEL` (default `qwen3.5:27b`), `OLLAMA_HOST` (default `http://127.0.0.1:11434`). Model bake-off on real sheets: `qwen3.5:27b` won (best recall/cleanest); `exaone3.5:7.8b` is a strong lighter pick; `qwen2.5vl:7b` was worst (truncates dense sheets). Reassembly is model-agnostic and sends `think: false` (qwen3.5 is a thinking model; output falls back to the `thinking` field). Feeding the image directly to the Ollama *vision* model crashed its runner on a real sheet — running reassembly as a **text** task on the Vision OCR output is why it's reliable.
- Required env vars: `ESV_API_KEY` (api.esv.org, free non-commercial), `TEMPLATE_KEY` (path to master `.key` template). Optional: `NTFY_TOPIC` (ntfy.sh topic for phone push on failure — leave blank to disable). Uploaded bulletin/sheet files land in a fixed `data/inbox/` (git-ignored; `worship_deck.web.app.INBOX_DIR`) — no env var, since files arrive via the upload form rather than an iCloud drop-folder. 봉헌 hymn slides are fetched online per song — there is no local hymn directory.
- Generating pdfplumber-readable Korean PDFs requires Playwright (`page.pdf()`); `fpdf2` with TTC fonts produces PDFs with 0 extractable chars.
- pdfplumber emits `Could not get FontBBox` log noise on Playwright-generated PDFs — suppress with `logging.disable(logging.WARNING)` around `pdfplumber.open()`.
- Real bulletins are **US Legal landscape** (14"×8.5" = 1008×612 pts). `sample_bulletin.pdf` matches this format; do not change the paper size.
- pdfplumber flattens multi-column PDFs: all text at the same Y level is merged into one extracted line (worship order rows appear alongside announcement text on the same line).
- Playwright landscape PDFs: `page-break-after: always` on a `.page` div at an exact page boundary inserts a blank trailing page — use a separate `.page-break` div between pages instead.
- Mock `httpx.get` in tests with `monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse())` and a minimal `_FakeResponse` class (see `tests/test_esv.py`). No `respx` or `pytest-httpx` needed.

## Coding guidelines

- **Ask before assuming.** State assumptions explicitly; surface ambiguity rather than resolving it silently.
- **Minimum code.** No unrequested features, abstractions, or configurability. If 200 lines could be 50, rewrite it.
- **Surgical edits.** Change only what the request requires. Don't touch adjacent code; note (don't delete) unrelated dead code.
- **Verify goals.** For multi-step tasks, define a check for each step and confirm it passes before moving on.
- **Never commit, push, or open PRs without explicit instruction.** After implementing changes, stop and let the user review locally first. Wait for "ship it", "commit", "/ship", or similar before any git operation.
