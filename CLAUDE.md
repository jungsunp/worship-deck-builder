# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

Builds a weekly worship deck for a Korean church's Sunday worship services, from one reviewed set of weekly content, in two targets: a **ProPresenter `.pro`** (primary — handed over as a single `.probundle` the operator imports on the church Mac) and a **Keynote `.key`** (fallback until full cutover, epic #184). The review app has one build button per target. The same deck is shared across all services (e.g. 9am and 11am). **A Mac hosts everything** (the web app, Apple Vision OCR at assemble); only the Keynote target also needs a **logged-in GUI session**, because Keynote automation needs the macOS window server — the `.pro` build is pure-Python protobuf. Phones reach the FastAPI web app privately over a **Tailscale** tailnet to upload files, review, and trigger builds; production runs on an always-on church Mac mini (v2 remote-access effort — issues #148–#162; see README "Remote access & deployment").

Per-section content sources (see `config/slide_map.yaml`):
- **Worship songs (찬양):** band **lead sheet** images shared via Kakao — often a multi-song medley with red arrangement marks (`V/C/B` sections, `×N` repeats, X-out skips, `→` segues). Only the **lyrics** are needed (the band runs the arrangement live from the sheets). The bulletin names the band, not the songs, so each sheet's title is detected from the OCR (tallest mostly-Hangul line; `lyrics/ocr_ko.swift` emits per-line heights) and **canonical lyrics are looked up on gasazip.com** ranked by OCR-fragment overlap (`lyrics/online.py`, #110). On no confident match the song comes back **empty**, carrying the scored candidates, and the operator picks one in review (#213) — OCR text is note-split and never used as slide text. No API key, no local model.
- **Choir (성가대):** lyrics arrive as **raw text** (title + composer line + lyric lines), pasted into the review app — not an image.
- **Offering hymn (봉헌):** a 찬송가 hymn identified in the **bulletin** by number/title/verses; the PowerPoint is **downloaded online** per song from **bibletoppt.com** (number-keyed token API, design `no-bg`; `hymn.py`) — not stored locally — then **all** slides are converted to PNG (LibreOffice `soffice` → poppler `pdftoppm`) and placed as-is. The slides are flat images with no verse text, so unwanted verses are dropped by the operator in review (#25), not auto-selected. The ProPresenter deck fetches the *same* hymn again in `hymn.PRO_DESIGN` (`design6`) into a `design6/` subdirectory and swaps the operator's kept pages for it by filename (#179) — `no-bg` renders a solid-white page that suits Keynote's background but not the white-on-dark `.pro` deck.

## Commands

```bash
pip install -e ".[dev]"
bash scripts/gen_proto.sh              # ProPresenter protobuf bindings (needs protoc) — git-ignored; rerun per checkout/worktree
python -m playwright install chromium  # only for scripts/make_fixtures.py (sample-bulletin PDF)
cp .env.example .env

ruff check src tests
pytest -m "not local_only"   # CI-safe; no Mac/Keynote needed
pytest -m local_only          # Mac + Keynote required
set -a && source .env && set +a  # load .env vars before pytest (live tests need API keys)
uvicorn worship_deck.web.app:app --host 127.0.0.1 --port 8787 --reload
./serve.sh          # the same server with .env loaded; run it from a worktree and it serves THAT
                    # worktree's src against the main checkout's .env/.venv/data (a worktree has
                    # none of those — all git-ignored). PORT=8788 ./serve.sh for a second one.
uvicorn worship_deck.web.app:app --host 0.0.0.0 --port 8787  # ad-hoc same-Wi-Fi testing only: hit http://<mac-lan-ip>:8787/ (needs macOS firewall "Allow"). Production binds loopback (127.0.0.1) and uses Tailscale Serve for off-network access — see README "Remote access & deployment" (v2, #148–#162).

python scripts/make_pro_demo.py --run YYYY-MM-DD [--bundle]  # the real weekly .pro (+ .probundle) from a reviewed run
python scripts/audit_pro_layout.py <deck.pro> [--all]        # does every .pro text box fit? (CoreText, like PP)
```

## Architecture

`pipeline.py` orchestrates five steps: bulletin PDF parse → lyric transcription (Vision OCR → title → gasazip lookup) → Bible verse lookup → **human review in web app** → build. `pipeline.run(date, target)` picks the builder:

- **`pro`** — `propresenter/build.py` serializes a fresh ProPresenter `Presentation` protobuf ground-up (no template, no landmark detection; `fill_*` append in service order) and `propresenter/bundle.py` packs it with its media into `data/drafts/draft-YYYY-MM-DD.probundle`. See `docs/propresenter-architecture.md`.
- **`keynote`** — `keynote/build.py` drives Keynote via AppleScript, editing a copy of `templates/master.key` in place → `data/drafts/draft-YYYY-MM-DD.key`.

Both write **native, editable text**, never rendered images; the only image slides are 봉헌 hymn pages and the deck's own artwork/media. **Builder-specific rules live next to the code** — `src/worship_deck/propresenter/CLAUDE.md` and `src/worship_deck/keynote/CLAUDE.md` load when you work in those directories.

`obs.py` wraps the pipeline with rotating-file logging (`logs/`), a per-run JSONL record (`logs/runs.jsonl`, phase `build` for Keynote, `build_pro` for ProPresenter), and optional phone push notifications via ntfy.sh (`NTFY_TOPIC`). All are git-ignored.

The web app (`web/app.py`) is API-only: pages are static HTML/CSS/JS files under `web/static/` served by FastAPI (no template engine — `review.html` reads its date from `location.pathname`); dynamic content uses small JSON endpoints + `fetch`-based JS, with shared design tokens in `web/static/app.css`. Match this — don't add Jinja2 or a JS build step.

The run is two-phase and web-driven: **assemble** (`web/app.py._assemble_async`: parse → lyric transcription → Bible verse lookup → hymn download, persisted to the per-run `store.py`) → **human review** (inline editors in the web app) → **build** (`POST /runs/<date>/build?target=keynote|pro` → `pipeline.run` loads the reviewed `ServiceData` from the store and drives the chosen builder). Both targets read the same reviewed run — only the build phase differs.

## Constraints

- `data/` is git-ignored. **Never commit it** — real bulletins contain member names and offering amounts.
- `tests/fixtures/` contains sanitized real bulletin data (member names/amounts scrubbed). Never commit unsanitized files. Regenerate with `python scripts/make_fixtures.py` (macOS only).
- `data/real-bulletin.pdf` and `data/real-sheet.png` — drop real files here for local testing.
- **ProPresenter bindings are generated, not committed.** `propresenter/pb/*_pb2.py` is git-ignored — run `bash scripts/gen_proto.sh` after checkout and in every worktree, or every `propresenter` test `importorskip`s into a false green (CI never generates them, so it never runs those tests). The vendored protos are pinned to PP 21.4 and verified on the church's 18.4 (#191). Read `docs/propresenter-architecture.md` before any `.pro` work.
- `local_only` marker gates any test needing macOS + Keynote or live API calls; CI runs on Ubuntu and skips them. Add `if not os.environ.get("KEY"): pytest.skip(...)` inside the test body too — the marker alone doesn't skip when running without `-m "not local_only"`.
- **Lyric transcription** is gasazip-only (canonical lyrics ranked by Apple Vision OCR fragments; unresolved sheets are picked by the operator in review). Don't reintroduce a local model — the Ollama fallback was removed in #213 because its output was discarded every week. Query-variant/throttle/budget gotchas: see `docs/gotchas.md`.
- **봉헌 hymn slide conversion** (`hymn.pptx_to_pngs`) shells out to LibreOffice `soffice` + poppler `pdftoppm`; bibletoppt needs a browser UA + ~5-min JWT — setup detail: see `docs/gotchas.md`.
- Required env vars: `ESV_API_KEY` (api.esv.org, free non-commercial), `TEMPLATE_KEY` (path to master `.key` template — Keynote target only). Optional: `NTFY_TOPIC` (ntfy.sh topic for phone push on failure — leave blank to disable). Uploaded bulletin/sheet files land in a fixed `data/inbox/` (git-ignored; `worship_deck.web.app.INBOX_DIR`) — no env var, since files arrive via the upload form rather than an iCloud drop-folder. 봉헌 hymn slides are fetched online per song — there is no local hymn directory.
- **PDF generation/parsing gotchas** (pdfplumber needs Playwright-made PDFs, FontBBox log noise, US-Legal landscape paper size, multi-column flattening, Playwright page-breaks) and **test/env one-offs** (`source .env` fails on the `INBOX_DIR` space; mock `httpx.get` without respx; `pytest` in a worktree tests the main checkout unless `PYTHONPATH=src`): see `docs/gotchas.md`.
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
