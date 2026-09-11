# Vendored ProPresenter protobuf definitions

These `.proto` files are a **pinned, unofficial** snapshot — reverse-engineered,
not from Renewed Vision. Only field *numbers* go on the wire, so a document
written against one schema opens on another as long as the numbers it uses
agree — which is why a deck generated against this 21.4 pin opens on the
church's 18.4 (verified below). A release that renumbered a field would break
that, so keep the pin explicit.

| | |
|---|---|
| ProPresenter version | **21.4** (build **352583705**) — see `version.txt` |
| Source repo | [greyshirtguy/ProPresenter7-Proto](https://github.com/greyshirtguy/ProPresenter7-Proto) |
| Source path | `autogen-proto/` (daily auto-generated, latest = installed PP) |
| Pinned commit | `1b63dda196eb7e079721a8a4a7e7773520cb5ad2` (commit msg: "Update protobufs for ProPresenter 21.4,352583705") |
| Vendored | 2026-06-30 |
| Verified on | ProPresenter **18.4** (302252046), church Mac mini #1, 2026-09-09 (#191) |

`google/protobuf/*.proto` here are the well-known types, kept only so `protoc`
can resolve imports offline; they are **not** compiled to Python (the `protobuf`
runtime already provides `google.protobuf.*_pb2`).

## Verified on the church's 18.4 (#191)

A real weekly deck — `draft-2026-09-06`, 165 slides in 20 groups, generated
against this 21.4 schema and handed over as a `.probundle` — imports into 18.4
and renders correctly: groups, group colors, slide labels, Korean RTF runs,
개역한글/ESV verse layout, 봉헌 hymn image pages and the backdrops. Diffing its
wire format against the copy 18.4 wrote back to its own library, four field
paths differ, none of them content:

| field | delta | why it doesn't matter |
|---|---|---|
| `Graphics.Text.Attributes.stroke_width` | dropped ×620 | value was `-0.0` — a 21.4 serializer default; we never set it |
| `Media.Metadata.color_format` | dropped ×84 | 21.4-era HDR enum, absent from 18.4's schema |
| `Media.Metadata.format` | 84 → 75 | PP re-wrote metadata for the 9 media it re-ingested on import |
| `ApplicationInfo` version stamp, one `custom_attributes` | dropped ×1 | PP restamps the writing app |

So the pin stays 21.4 — the version the dev Mac runs (18.4 crashes there) — and
`build.PP_VERSION` keeps stamping `(21, 4)`. The church mini needs no `protoc`;
it only opens `.probundle` files.

## Re-vendoring

Only needed if a ProPresenter release fails to open a generated deck:

1. Read the version: `defaults read ~/Applications/ProPresenter.app/Contents/Info.plist CFBundleShortVersionString CFBundleVersion`
2. Find the matching greyshirtguy commit (its `autogen-proto/version.txt` equals `<short>,<build>`).
3. Re-copy `autogen-proto/` over `proto/` and run `scripts/gen_proto.sh`.
4. Build a real weekly deck (`scripts/make_pro_demo.py --run <date> --bundle`) and confirm it opens and renders on the church's ProPresenter.
