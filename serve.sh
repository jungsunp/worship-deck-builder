#!/usr/bin/env bash
# Start the worship-deck review/build web app.
# Frees port 8787, loads .env, then runs uvicorn bound to all interfaces
# (so an iPhone can reach it over Wi-Fi/Tailscale).
set -euo pipefail
cd "$(dirname "$0")"

lsof -ti:8787 | xargs kill -9 2>/dev/null || true
set -a && source .env && set +a
exec .venv/bin/uvicorn worship_deck.web.app:app --host 0.0.0.0 --port 8787 "$@"
