# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

Builds a weekly Keynote worship deck for a Korean church's Sunday worship services. The same deck is shared across all services (e.g. 9am and 11am). **Requires a Mac that is powered on and logged in** — Keynote automation needs the macOS window server. Phones reach the FastAPI web app privately over a **Tailscale** tailnet to upload files, review, and trigger builds; production runs on an always-on church Mac mini (v2 remote-access effort — issues #148–#162; see README "Remote access & deployment").

Per-section content sources (see `config/slide_map.yaml`):
- **Worship songs (찬양):** band **lead sheet** images shared via Kakao — often a multi-song medley with red arrangement marks (`V/C/B` sections, `×N` repeats, X-out skips, `→` segues). Only the **lyrics** are needed (the band runs the arrangement live from the sheets). The bulletin names the band, not the songs, so each sheet's title is detected from the OCR (tallest mostly-Hangul line; `lyrics/ocr_ko.swift` emits per-line heights) and **canonical lyrics are looked up on gasazip.com** ranked by OCR-fragment overlap (`lyrics/online.py`, #110). On no confident match the song comes back **empty**, carrying the scored candidates, and the operator picks one in review (#213) — OCR text is note-split and never used as slide text. No API key, no local model.
- **Choir (성가대):** lyrics arrive as **raw text** (title + composer line + lyric lines), pasted into the review app — not an image.
- **Offering hymn (봉헌):** a 찬송가 hymn identified in the **bulletin** by number/title/verses; the PowerPoint is **downloaded online** per song from **bibletoppt.com** (number-keyed token API, design `no-bg`; `hymn.py`) — not stored locally — then **all** slides are converted to PNG (LibreOffice `soffice` → poppler `pdftoppm`) and placed as-is. The slides are flat images with no verse text, so unwanted verses are dropped by the operator in review (#25), not auto-selected. The ProPresenter deck fetches the *same* hymn again in `hymn.PRO_DESIGN` (`design6`) into a `design6/` subdirectory and swaps the operator's kept pages for it by filename (#179) — `no-bg` renders a solid-white page that suits Keynote's background but not the white-on-dark `.pro` deck.

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
uvicorn worship_deck.web.app:app --host 0.0.0.0 --port 8787  # ad-hoc same-Wi-Fi testing only: hit http://<mac-lan-ip>:8787/ (needs macOS firewall "Allow"). Production binds loopback (127.0.0.1) and uses Tailscale Serve for off-network access — see README "Remote access & deployment" (v2, #148–#162).
```

## Architecture

`pipeline.py` orchestrates five steps: bulletin PDF parse → lyric transcription (Vision OCR → title → gasazip lookup) → Bible verse lookup → **human review in web app** → AppleScript Keynote build (duplicate section slides + set native text) → `data/drafts/draft-YYYY-MM-DD.key`.

**Key design:** the church builds slides as **native Keynote text boxes**, so the builder edits them in place rather than rendering images. Starting from the template deck (`templates/master.key`, a real recent deck), the AppleScript build step sets each slide's text runs and duplicates section slides to fit the week's content (lyrics/announcements expand). The **only image slides** are offering-hymn pages (downloaded online as a 찬송가 PowerPoint, converted to images), band lead sheets, and media (e.g. countdown video) — placed as-is. There is no HTML/PNG rendering step.

`obs.py` wraps the pipeline with rotating-file logging (`logs/`), a per-run JSONL record (`logs/runs.jsonl`), and optional phone push notifications via ntfy.sh (`NTFY_TOPIC`). All are git-ignored.

Section structure, content sources, and render modes are declared in `config/slide_map.yaml`.

The web app (`web/app.py`) is API-only: pages are static HTML/CSS/JS files under `web/static/` served by FastAPI (no template engine — `review.html` reads its date from `location.pathname`); dynamic content uses small JSON endpoints + `fetch`-based JS, with shared design tokens in `web/static/app.css`. Match this — don't add Jinja2 or a JS build step.

The run is two-phase and web-driven: **assemble** (`web/app.py._assemble_async`: parse → lyric transcription → Bible verse lookup, persisted to the per-run `store.py`) → **human review** (inline editors in the web app) → **build** (`pipeline.run` loads the reviewed `ServiceData` from the store and drives Keynote). All five steps are implemented; `parse`, `bible`, `lyrics.chunk()`, and the `keynote` builder all shipped (#62–#95).

`keynote/build.py` is a library of small AppleScript primitives (`save_draft`/`finalize_draft`, `duplicate_slide`/`duplicate_block`, `delete_slides`, `place_image`, `set_*_slide`, `read_verse_boxes`) plus per-section `fill_*` functions (`fill_verse_slides`, `fill_song_slides`, `fill_worship_songs`, `fill_choir_slides`, `fill_announcement_slides`), composed by `build(data, template_key, out_key)`; `export_pdf` renders a draft for review. AppleScript sources live in `keynote/applescript/`.

## Constraints

- `data/` is git-ignored. **Never commit it** — real bulletins contain member names and offering amounts.
- `tests/fixtures/` contains sanitized real bulletin data (member names/amounts scrubbed). Never commit unsanitized files. Regenerate with `python scripts/make_fixtures.py` (macOS only).
- `data/real-bulletin.pdf` and `data/real-sheet.png` — drop real files here for local testing. `TEMPLATE_KEY` env var points to the master Keynote template.
- `templates/master.key` is git-ignored (large, church media). Place locally, never commit.
- `build()` locates every section by **landmark-text detection at build time** (#98): one `dump_slide_texts` pass over the open draft, then `keynote/anchors.py:detect_anchors` derives every anchor + section size from the recurring divider headings (예배의 부름 / 고백의 찬양 / 사도신경 / 성가대 찬양 / 봉 헌 / 교회 소식), the `[<ref>, 개역한글]` verse-label slides, and the 파송의 노래/축도/주기도문 closing — failing loud (named section + candidate slides) before any edit when a landmark is missing or ambiguous. `config/slide_map.yaml` documents the reference numbers for humans only (not read by code). After replacing `master.key`, run `pytest -m local_only -k detect_anchors_live` (see README "Replacing the template").
- `local_only` marker gates any test needing macOS + Keynote or live API calls; CI runs on Ubuntu and skips them. Add `if not os.environ.get("KEY"): pytest.skip(...)` inside the test body too — the marker alone doesn't skip when running without `-m "not local_only"`. Live Keynote `local_only` tests are slow (~60–90s, real app open/save) — run them in the background.
- **Keynote AppleScript gotchas** (osascript primitives, open-once/save-once lifecycle, aspect-fill images, PNG-export verify, deck-text diffing) — read before any AppleScript work: see `docs/gotchas.md`.
- **Lyric transcription** is gasazip-only (canonical lyrics ranked by Apple Vision OCR fragments; unresolved sheets are picked by the operator in review). Don't reintroduce a local model — the Ollama fallback was removed in #213 because its output was discarded every week. Query-variant/throttle/budget gotchas: see `docs/gotchas.md`.
- **봉헌 hymn slide conversion** (`hymn.pptx_to_pngs`) shells out to LibreOffice `soffice` + poppler `pdftoppm`; bibletoppt needs a browser UA + ~5-min JWT — setup detail: see `docs/gotchas.md`.
- Required env vars: `ESV_API_KEY` (api.esv.org, free non-commercial), `TEMPLATE_KEY` (path to master `.key` template). Optional: `NTFY_TOPIC` (ntfy.sh topic for phone push on failure — leave blank to disable). Uploaded bulletin/sheet files land in a fixed `data/inbox/` (git-ignored; `worship_deck.web.app.INBOX_DIR`) — no env var, since files arrive via the upload form rather than an iCloud drop-folder. 봉헌 hymn slides are fetched online per song — there is no local hymn directory.
- **PDF generation/parsing gotchas** (pdfplumber needs Playwright-made PDFs, FontBBox log noise, US-Legal landscape paper size, multi-column flattening, Playwright page-breaks) and **test/env one-offs** (`source .env` fails on the `INBOX_DIR` space; mock `httpx.get` without respx): see `docs/gotchas.md`.
- **Remote access is Tailscale-only (v2).** The app is never exposed to the public internet: uvicorn binds loopback (`127.0.0.1`), `tailscale serve` fronts it over HTTPS on the tailnet, and per-user identity comes from Serve's `Tailscale-User-Login` header (no app password). Don't add a `--host 0.0.0.0` production path, a public tunnel (Cloudflare etc.), or an app login/password system — those were considered and rejected. See README "Remote access & deployment" and issues #148–#162.
- `ruff check src tests` lints the whole tree — with concurrent sessions it may fail on another session's uncommitted files. Lint only your changed paths (`ruff check <file>...`) to check your own work.

## Coding guidelines

- **Ask before assuming.** State assumptions explicitly; surface ambiguity rather than resolving it silently.
- **Minimum code.** No unrequested features, abstractions, or configurability. If 200 lines could be 50, rewrite it.
- **Surgical edits.** Change only what the request requires. Don't touch adjacent code; note (don't delete) unrelated dead code.
- **Verify goals.** For multi-step tasks, define a check for each step and confirm it passes before moving on.
- **Never commit, push, or open PRs without explicit instruction.** After implementing changes, stop and let the user review locally first. Wait for "ship it", "commit", "/ship", or similar before any git operation.
  - `/ship` **is** that instruction, and it authorizes the whole loop its skill defines — branch → commit → push → open PR → watch CI → merge — including when the `ship` subagent runs it. Merging a green PR under `/ship` is expected, not an unreviewed merge; don't flag it as one. Anything beyond that loop (force-push, rewriting history, touching other branches, releases) still needs its own say-so.
  - Because concurrent sessions share this working tree, stage an explicit file list — never `git add -A`/`.` (see the `ruff` note above).
