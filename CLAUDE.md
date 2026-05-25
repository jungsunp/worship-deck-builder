# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

Builds a weekly Keynote worship deck for a Korean church's Sunday worship services from a bulletin PDF + lyric sheet images. The same deck is shared across all services (e.g. 9am and 11am). **Requires a Mac that is powered on and logged in** — Keynote automation needs the macOS window server. An iPhone reaches the FastAPI web app over Tailscale to review and trigger builds.

## Commands

```bash
pip install -e ".[dev]"
python -m playwright install chromium  # HTML→PNG rendering
cp .env.example .env

ruff check src tests
pytest -m "not local_only"   # CI-safe; no Mac/Keynote needed
pytest -m local_only          # Mac + Keynote required
uvicorn worship_deck.web.app:app --host 127.0.0.1 --port 8787 --reload
```

## Architecture

`pipeline.py` orchestrates six steps: bulletin PDF parse → Claude vision lyric transcription → Bible verse lookup → **human review in web app** → Playwright HTML→PNG render → AppleScript Keynote build → `data/drafts/draft-YYYY-MM-DD.key`.

**Key design:** all congregation slides are flattened text-on-background PNGs (not native Keynote text boxes), so one renderer covers every slide type. Hymn slides (`offering_hymn`) are the only exception — pre-existing images placed as-is.

Section structure, content sources, and render modes are declared in `config/slide_map.yaml`.

All core modules are currently stubs (`raise NotImplementedError`). Implement in order: `parse` → `bible` → `lyrics` → `render` → `keynote`.

## Constraints

- `data/` is git-ignored. **Never commit it** — real bulletins contain member names and offering amounts.
- `tests/fixtures/` contains sanitized real bulletin data (member names/amounts scrubbed). Never commit unsanitized files. Regenerate with `python scripts/make_fixtures.py` (macOS only).
- `data/real-bulletin.pdf` and `data/real-sheet.png` — drop real files here for local testing. `TEMPLATE_KEY` env var points to the master Keynote template.
- `templates/master.key` is git-ignored (large, church media). Place locally, never commit.
- `local_only` marker gates any test needing macOS + Keynote; CI runs on Ubuntu and skips them.
- Required env vars: `ANTHROPIC_API_KEY` (lyric transcription), `ESV_API_KEY` (api.esv.org, free non-commercial).
- Generating pdfplumber-readable Korean PDFs requires Playwright (`page.pdf()`); `fpdf2` with TTC fonts produces PDFs with 0 extractable chars.
- pdfplumber emits `Could not get FontBBox` log noise on Playwright-generated PDFs — suppress with `logging.disable(logging.WARNING)` around `pdfplumber.open()`.
- Real bulletins are **US Legal landscape** (14"×8.5" = 1008×612 pts). `sample_bulletin.pdf` matches this format; do not change the paper size.
- pdfplumber flattens multi-column PDFs: all text at the same Y level is merged into one extracted line (worship order rows appear alongside announcement text on the same line).
- Playwright landscape PDFs: `page-break-after: always` on a `.page` div at an exact page boundary inserts a blank trailing page — use a separate `.page-break` div between pages instead.

## Coding guidelines

- **Ask before assuming.** State assumptions explicitly; surface ambiguity rather than resolving it silently.
- **Minimum code.** No unrequested features, abstractions, or configurability. If 200 lines could be 50, rewrite it.
- **Surgical edits.** Change only what the request requires. Don't touch adjacent code; note (don't delete) unrelated dead code.
- **Verify goals.** For multi-step tasks, define a check for each step and confirm it passes before moving on.
