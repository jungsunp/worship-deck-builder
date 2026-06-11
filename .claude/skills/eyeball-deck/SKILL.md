---
name: eyeball-deck
description: Build a draft worship deck from the template, fill a section (worship-song lyrics or Bible verses) with sample or real content, and open it in Keynote for visual ("eyeball") review. Use when the user wants to verify generated slides in an actual .key file before shipping — not just trust PNG renders or tests.
---

# Eyeball a deck section in Keynote

Produce a real `.key` the user can open and inspect, then point them at the slides to check.
Backs the "verify before shipping" step for the native-text Keynote builder (#14 verses, #15
worship songs). The CI-safe tests and PNG renders prove correctness headlessly; this skill is for
when the user wants to look at the actual deck.

## How to run

A bundled helper does the whole thing (launch Keynote → save a draft copy → fill one section →
open it). Run it from the repo root with the project's venv active:

```bash
python .claude/skills/eyeball-deck/build_eyeball.py song            # sample worship song
python .claude/skills/eyeball-deck/build_eyeball.py verse           # sample 예배의 부름 verses
python .claude/skills/eyeball-deck/build_eyeball.py announce        # 교회소식 from the sample bulletin
python .claude/skills/eyeball-deck/build_eyeball.py hymn            # 봉헌 hymn 220 downloaded online
python .claude/skills/eyeball-deck/build_eyeball.py confession      # 고백의 찬양 with a sample song
```

Customize content / placement:

```bash
# a specific song into the worship block (title slide 7, 10 template lyric slides)
python .claude/skills/eyeball-deck/build_eyeball.py song \
    --title "주 은혜임을" --line "내 평생에 가는 길" --line "순탄하여 늘 잔잔한 강 같든지" \
    --at 7 --existing 10

# real verse lookup (needs ESV_API_KEY) into the sermon block (slides 129–132)
python .claude/skills/eyeball-deck/build_eyeball.py verse --ref "눅 22:14-24" --at 129 --existing 4

# 교회소식 parsed from a real bulletin PDF (title + reflowed detail per item)
python .claude/skills/eyeball-deck/build_eyeball.py announce --bulletin data/real-bulletin.pdf
# or override the content explicitly
python .claude/skills/eyeball-deck/build_eyeball.py announce --item "1. 새가족 환영회" --item "2. 여름성경학교 안내"

# 봉헌 hymn: download a specific 찬송가 number online (needs soffice + poppler + network)
python .claude/skills/eyeball-deck/build_eyeball.py hymn --number 220
# or place your own PNGs (skips the download)
python .claude/skills/eyeball-deck/build_eyeball.py hymn --image a.png --image b.png
```

Useful flags: `--out <path>` (default `/tmp/draft-eyeball.key`; pass
`data/drafts/draft-eyeball.key` to keep a copy in the repo's git-ignored drafts dir),
`--template <path>` (default `$TEMPLATE_KEY`), `--no-open` (build without opening).
The script prints the slide range to review and opens the deck.

## Section anchors in the template (master.key)

- **Worship songs** — song 1: title slide **7**, lyric slides 8–17 (`--at 7 --existing 10`).
  Other songs in the sample template start at 19 and 37.
- **Verses** — 예배의 부름: slide **48** (`--existing 1`); 말씀 (sermon): slides **129–132**
  (`--at 129 --existing 4`).
- **고백의 찬양** — divider **57** ("고백의 찬양" heading + bracketed title), blank 58, title
  banner 59, lyric slides 60–67, trailing blank 68 (`--at 57`; the 8-slide lyric block is
  hardcoded like choir's).
- **Announcements (교회소식)** — item slides **117–121** (`--at 117`, default `--existing 5`); each
  is one item, parsed from the bulletin (`announcement_blocks`: numbered title + reflowed detail).
  Slides 113–116 are section-title/motto headers (not touched); slide 122 is blank.
- **Offering hymn (봉헌)** — section anchor **97** (`--at 97`). Slides 97–98 are the 봉헌
  title/intro text slides; last week's hymn *page images* follow (99–106 in the current template).
  The block size **varies weekly** (a different hymn has a different page count), so `fill_hymn_slides`
  does NOT take an `--existing`: `hymn_image_block` auto-detects last week's pages (the contiguous
  image slides at/after 97) and replaces exactly those, leaving the title/intro slides alone. Each
  new page is placed with `clear_existing=True`, deleting last week's page on that slide first
  (replace, not stack).

(Confirm against the current template if it changed — probe with a throwaway `osascript` that
dumps each slide's on-canvas text-item positions, as in `tests/test_keynote_build.py`.)

## What to tell the user after building

Name the exact slides to open and what each should show, e.g. for `song --at 7`:
- slide **7**: title band = the song title;
- slides **8..**: each a ≤2-line lyric chunk;
- the slide **right after** the filled block = the *next* section's slide (proves surplus
  template slides were trimmed — no leftover).

For `announce --at 117`: slides **117..** each carry one announcement item — paragraph 1 is the
title (rendered **gold**), the rest is the detail (rendered **white**), matching master.key. The
slide right after the block is the next section (proves surplus item slides were trimmed).

For `hymn`: the script prints the detected page range (e.g. "Replaced last week's hymn pages
(slides 99–106) with 9 new …"). Tell the user to check: the 봉헌 **title/intro** slides (97–98)
are **unchanged**; the detected block now shows **this week's** hymn pages, full-bleed; and the
slide **right after** the block is the next section (환영 및 인사) — no leftover hymn pages, and no
old page peeking out from under a new one (each replaced slide has exactly one image).

## Keynote stability rules (do not skip — these are why earlier runs failed)

- **Requires a Mac that is powered on and logged in** (Keynote needs the window server).
- **Launch Keynote and let it settle before driving it.** The helper does `open -a Keynote`,
  waits, and polls `get name` until it answers. Firing an Apple event at a cold app gives `-609`.
- **Never force-quit Keynote** (`quit` / `killall` / `pkill osascript`) to "reset" a stuck run.
  That corrupts the scripting bridge → repeated `-609` "connection is invalid". A clean relaunch
  is the only reliable reset. The helper closes stale *documents* (not the app) before building.
- The save of the ~30 MB `master.key` is slow and **times out at 120s** (hardcoded in
  `build.py`'s `_run_osascript`) when writing into the project dir under an editor's file
  watcher. The default `--out /tmp/...` avoids this; only use `--out data/drafts/...` when you
  need to keep the file and accept the flakiness (close stale docs and retry if it times out).
- Leave no orphans: if you spawned a background build that timed out, `pkill -f
  build_eyeball.py` and re-check before retrying, so the next run isn't serialized behind a stuck
  osascript holding Keynote.

## Notes

- The draft is disposable (regenerate any time); `data/` is git-ignored — never commit drafts.
- This skill only *verifies*; it does not ship. Shipping is the user's call (`/ship`).
