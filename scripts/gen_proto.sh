#!/usr/bin/env bash
# Regenerate ProPresenter protobuf Python bindings from the vendored .proto files.
#
# The .proto files under src/worship_deck/propresenter/proto/ are a pinned snapshot
# of greyshirtguy/ProPresenter7-Proto's autogen-proto, matching the installed
# ProPresenter version (see proto/version.txt and proto/SOURCE.md). They are
# UNOFFICIAL: re-vendor + regenerate only if a ProPresenter release fails to open
# a generated deck (the 21.4 pin opens on the church's 18.4, #191).
#
# Requires protoc (`brew install protobuf`). The generated *_pb2.py land in
# src/worship_deck/propresenter/pb/ and are git-ignored — rerun this after every
# fresh checkout and in every new worktree. Only generating needs protoc; the
# church mini that opens the decks needs none of this.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
proto_dir="$here/src/worship_deck/propresenter/proto"
out_dir="$here/src/worship_deck/propresenter/pb"

command -v protoc >/dev/null || { echo "protoc not found — run: brew install protobuf" >&2; exit 1; }

# Clear prior output but keep the hand-written package files (__init__.py, .gitignore).
mkdir -p "$out_dir"
find "$out_dir" -name '*_pb2.py' -delete
find "$out_dir" -mindepth 1 -type d -exec rm -rf {} +

# Compile only the rv/ProPresenter protos (top-level *.proto). google/protobuf/*
# well-known types stay on the include path so imports resolve, but are NOT
# generated — the protobuf runtime already ships them as google.protobuf.*_pb2.
protoc \
  --proto_path="$proto_dir" \
  --python_out="$out_dir" \
  "$proto_dir"/*.proto

echo "Generated $(ls "$out_dir"/*_pb2.py | wc -l | tr -d ' ') *_pb2.py into pb/"
