#!/usr/bin/env bash
# Start the worship-deck review/build web app with the project env loaded.
#
# Solves the recurring "ESV_API_KEY not set" bug: uvicorn FREEZES
# its environment at launch and does NOT auto-load .env, so the env must be exported
# into this shell *before* exec'ing uvicorn. Editing .env after the server is up does
# nothing until you stop it and run this again.
#
# Usage:  .claude/skills/serve/serve.sh [extra uvicorn args, e.g. --reload]
set -euo pipefail

# repo root, regardless of where this is invoked from (.claude/skills/serve/ -> root)
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../../.."

# 1. Load .env (all vars). `set -a` exports everything sourced; safe here since this
#    .env has no unquoted-space values (the INBOX_DIR caveat in CLAUDE.md is about a
#    var that does not live in .env).
if [[ -f .env ]]; then
  set -a; source .env; set +a
else
  echo "✗ no .env in $(pwd) — copy .env.example to .env and fill it in" >&2
  exit 1
fi

# 2. Fail fast on the two things that silently break a real run.
[[ -n "${ESV_API_KEY:-}" ]] || {
  echo "✗ ESV_API_KEY is empty — Bible verse lookup will 500 during assemble" >&2
  exit 1
}
echo "✓ ESV_API_KEY loaded"

# 3. Launch. Bind 0.0.0.0 so the iPhone can reach it over Wi-Fi / Tailscale (#28).
host="${WEB_HOST:-0.0.0.0}"
port="${WEB_PORT:-8787}"
lan_ip="$(ipconfig getifaddr en0 2>/dev/null || echo '<mac-lan-ip>')"
echo "→ http://127.0.0.1:${port}/        (this Mac)"
echo "→ http://${lan_ip}:${port}/   (iPhone on same Wi-Fi — needs macOS firewall 'Allow')"
echo "  off-network access is via Tailscale (#28)"

# Prefer the project venv's uvicorn so an un-activated shell still works.
if [[ -x .venv/bin/uvicorn ]]; then
  uvicorn_bin=.venv/bin/uvicorn
else
  uvicorn_bin=uvicorn
fi
exec "$uvicorn_bin" worship_deck.web.app:app --host "$host" --port "$port" "$@"
