#!/usr/bin/env bash
# Start the worship-deck review/build web app.
# Frees the port, loads .env, then runs uvicorn bound to all interfaces
# (so an iPhone can reach it over Wi-Fi/Tailscale).
#
# Run it from a git worktree and it serves *that worktree's* code against the main
# checkout's .env / .venv / data — a worktree has none of those (all git-ignored), which
# is why running a worktree copy of this script used to die on "`.env`: No such file".
# Set PORT to run several at once, one per worktree:  PORT=8788 ./serve.sh
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
# --git-common-dir points at the *main* checkout's .git even from inside a worktree. It comes
# back absolute from a worktree but bare ".git" from the main checkout, so resolve it from
# $here rather than from wherever the caller happened to be standing.
main="$(cd "$here" && cd "$(git rev-parse --git-common-dir)/.." && pwd)"
cd "$main"

port="${PORT:-8787}"
lsof -ti:"$port" | xargs kill -9 2>/dev/null || true
set -a && source .env && set +a
# The venv installs worship_deck editable from the main checkout, so this is what puts a
# worktree's branch ahead of it; from the main checkout itself it is a harmless no-op.
export PYTHONPATH="$here/src"
exec .venv/bin/uvicorn worship_deck.web.app:app --host 0.0.0.0 --port "$port" "$@"
