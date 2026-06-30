# Vendored ProPresenter protobuf definitions

These `.proto` files are a **pinned, unofficial** snapshot — reverse-engineered,
not from Renewed Vision. They are **version-sensitive**: they must match the
ProPresenter build installed on the machine that opens the generated `.pro`
files, or documents may fail to load or render wrong.

| | |
|---|---|
| ProPresenter version | **21.4** (build **352583705**) — see `version.txt` |
| Source repo | [greyshirtguy/ProPresenter7-Proto](https://github.com/greyshirtguy/ProPresenter7-Proto) |
| Source path | `autogen-proto/` (daily auto-generated, latest = installed PP) |
| Pinned commit | `1b63dda196eb7e079721a8a4a7e7773520cb5ad2` (commit msg: "Update protobufs for ProPresenter 21.4,352583705") |
| Vendored | 2026-06-30 |

`google/protobuf/*.proto` here are the well-known types, kept only so `protoc`
can resolve imports offline; they are **not** compiled to Python (the `protobuf`
runtime already provides `google.protobuf.*_pb2`).

## Upgrading ProPresenter

When the church Mac mini's ProPresenter is upgraded, re-pin:

1. Read the new version: `defaults read ~/Applications/ProPresenter.app/Contents/Info.plist CFBundleShortVersionString CFBundleVersion`
2. Find the matching greyshirtguy commit (its `autogen-proto/version.txt` equals `<short>,<build>`).
3. Re-copy `autogen-proto/` over `proto/` and run `scripts/gen_proto.sh`.
4. Re-verify the hello-world round-trip opens in the new ProPresenter.
