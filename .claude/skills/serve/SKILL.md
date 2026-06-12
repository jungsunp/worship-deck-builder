---
name: serve
description: Start the worship-deck review/build web app (FastAPI/uvicorn) with the project .env loaded, so Bible lookups and lyric transcription actually work and an iPhone can reach it over Wi-Fi/Tailscale. Use whenever the user wants to "start/run the server", or after an assemble fails with "ESV_API_KEY not set" or Ollama using the wrong model.
---

# Start the web app

The review/build app is a long-running FastAPI server (inline-HTML pages + JSON endpoints).
The operator hits it from an iPhone to review the week's auto-detected content and trigger the
Keynote build.

## How to run

One bundled launcher does everything (load `.env` → validate → print the phone URL → exec
uvicorn). From the repo root:

```bash
.claude/skills/serve/serve.sh                # 0.0.0.0:8787 — phone/LAN access
.claude/skills/serve/serve.sh --reload       # add local-dev auto-reload (drop it for phone use)
```

It binds `0.0.0.0` so an iPhone on the same Wi-Fi can reach `http://<mac-lan-ip>:8787/` (the
script prints the exact URL); off-network access is via Tailscale (#28). Host/port come from
`WEB_HOST`/`WEB_PORT` in `.env`, defaulting to `0.0.0.0:8787`.

When asked to start the server, run this with `run_in_background: true` (it blocks), then report
the URLs it printed.

## Why a launcher and not a bare `uvicorn` command

This is the bug that has bitten twice: **uvicorn freezes its environment at startup and does NOT
auto-load `.env`.** Launching `uvicorn …` from a shell that never exported the env gives a server
where:

- `ESV_API_KEY` is empty → assemble dies with `RuntimeError: ESV_API_KEY environment variable is
  not set` at the Bible-verse step;
- a non-default `OLLAMA_MODEL`/`OLLAMA_HOST` set in `.env` is silently ignored — lyric
  transcription uses the code default (`qwen3:14b`) instead.

Editing `.env` while the server is already up changes nothing — you must stop it and start again.
The launcher exports the whole `.env` (`set -a; source .env; set +a`) **before** exec'ing uvicorn,
fail-fasts if `ESV_API_KEY` is empty, echoes the active `OLLAMA_MODEL`, and warns if Ollama isn't
responding.

## Prerequisites (one-time)

- `pip install -e ".[dev]"` into the project venv (the script prefers `.venv/bin/uvicorn`).
- `.env` filled in (`ESV_API_KEY`, `TEMPLATE_KEY`; `OLLAMA_MODEL` defaults to `qwen3:14b`).
- Ollama running for the assemble step: `ollama serve` + `ollama pull qwen3:14b`. The script
  only warns if it's down — reviewing/building an already-assembled run doesn't need it.
- For phone access: macOS firewall set to "Allow" for the Python/uvicorn process; same Wi-Fi, or
  Tailscale when off-network.

## After starting

Tell the user the local + LAN URLs the script printed, and that editing `.env` later requires a
restart (re-run this skill) to take effect.
