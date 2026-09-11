# Keynote builder — fallback target

Loaded when you work under `src/worship_deck/keynote/`. The Keynote `.key` is the **fallback**
build target (`pipeline.run(date, "keynote")`, the review page's `Keynote 덱` button); ProPresenter
is primary — see the root `CLAUDE.md`. Unlike the `.pro` build, this one needs a Mac with a
**logged-in GUI session**: Keynote automation needs the macOS window server.

- **Key design:** the church builds slides as **native Keynote text boxes**, so the builder edits them in place rather than rendering images. Starting from the template deck (`templates/master.key`, a real recent deck; `TEMPLATE_KEY` points to it), the AppleScript build step sets each slide's text runs and duplicates section slides to fit the week's content (lyrics/announcements expand). The **only image slides** are offering-hymn pages (bibletoppt `no-bg`, converted to images), band lead sheets, and media (e.g. countdown video) — placed as-is. There is no HTML/PNG rendering step.
- `build.py` is a library of small AppleScript primitives (`save_draft`/`finalize_draft`, `duplicate_slide`/`duplicate_block`, `delete_slides`, `place_image`, `set_*_slide`, `read_verse_boxes`) plus per-section `fill_*` functions (`fill_verse_slides`, `fill_song_slides`, `fill_worship_songs`, `fill_choir_slides`, `fill_announcement_slides`), composed by `build(data, template_key, out_key)`; `export_pdf` renders a draft for the phone's review preview. AppleScript sources live in `applescript/`.
- `templates/master.key` is git-ignored (large, church media). Place locally, never commit.
- `build()` locates every section by **landmark-text detection at build time** (#98): one `dump_slide_texts` pass over the open draft, then `anchors.py:detect_anchors` derives every anchor + section size from the recurring divider headings (예배의 부름 / 고백의 찬양 / 사도신경 / 성가대 찬양 / 봉 헌 / 교회 소식), the `[<ref>, 개역한글]` verse-label slides, and the 파송의 노래/축도/주기도문 closing — failing loud (named section + candidate slides) before any edit when a landmark is missing or ambiguous. `config/slide_map.yaml` documents the reference numbers for humans only (not read by code). After replacing `master.key`, run `pytest -m local_only -k detect_anchors_live` (see README "Replacing the template").
- **Keynote AppleScript gotchas** (osascript primitives, open-once/save-once lifecycle, aspect-fill images, PNG-export verify, deck-text diffing) — read before any AppleScript work: see `docs/gotchas.md`.
- Live Keynote `local_only` tests are slow (~60–90s, real app open/save) — run them in the background.
