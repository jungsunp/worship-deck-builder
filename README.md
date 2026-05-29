# Worship Deck Builder

Automates the weekly update of the Keynote deck used in a Korean church's Sunday worship
service. The same deck is shared across all services (e.g. 9am and 11am).

Each week the deck is rebuilt from a template using:
- the weekly **bulletin PDF** (worship order, announcements, Bible references, sermon title,
  and the 봉헌 offering-hymn 찬송가 number/title/verses),
- **worship-band lead sheets** (images shared via Kakao) — often a multi-song medley with
  red arrangement marks (section order, ×N repeats, X-out skips, → segues),
- **성가대 choir lyrics** as raw text (pasted into the review app),
- **봉헌 (offering) hymn slides** downloaded online as a 찬송가 PowerPoint per song,
- occasional **last-minute text updates**.

The tool produces a **draft deck for human review** — it never auto-publishes.

## The one hard constraint: a Mac must be on

Native Keynote can only be driven on a Mac that is **powered on and logged in** (Keynote
automation needs the macOS window server). So:

- **The Mac is the worker** — it runs Keynote and builds the deck.
- **Your iPhone is the remote** — files arrive via an **iCloud drop-folder**, and a small
  **mobile web app** (reached privately over Tailscale) lets you review/reorder songs and
  tap *Generate*.

To run while away, the Mac must stay awake (scheduled wake / Tailscale wake-on-LAN).

## Architecture

```
KakaoTalk ──(v1: you save files)──► iCloud inbox ──► [ MAC WORKER ]
                                                         │
   bulletin.pdf ─► parse/bulletin.py ─► worship order, announcements, refs, title,
                                       봉헌 hymn (찬 number/title/verses)
   band lead sheets ─► lyrics/transcribe.py (Claude vision) ─► lyric lines + arrangement
   choir lyrics (raw text) ─► strip title/composer ─► chunk into ≤2-line slides
   봉헌 hymn ─► download 찬송가 PPT online ─► slides → PNG
   Bible refs ─► bible/verses.py ─► 개역한글 + ESV verse text
                                                         │
                          render/render.py  (data + bg template ─► PNG)
                                                         │
                          keynote/build.py  (AppleScript: fresh deck from template,
                                             place rendered PNGs + downloaded hymn slides)
                                                         │
                                            data/drafts/draft-YYYY-MM-DD.key  + PDF preview
                                                         │
                          web/app.py  ◄── iPhone review / reorder / Generate / preview
```

Key insight: the congregation-facing slides (intro/ending date, Bible verses, worship
lyrics, announcements) are **flattened text-on-background images**, not native text boxes.
So one **slide renderer** (data + per-type background template → PNG) covers all of them.
봉헌 (offering) hymn slides are the exception — they are downloaded online as a 찬송가
PowerPoint per song, converted to images, and placed as-is.

## Slide map

See [`config/slide_map.yaml`](config/slide_map.yaml) — it encodes which template sections
change weekly and where their content comes from.

## Setup (to be fleshed out)

- Python 3.11+ recommended (system Python 3.9 is old; install via Homebrew).
- macOS with Keynote installed; grant Terminal/automation permission to control Keynote.
- ESV API key (free, non-commercial) for English verse text — see `.env.example`.
- Anthropic API key for lyric transcription from sheet images.
- Tailscale for reaching the web app from your phone.

## Privacy

This handles **church members' data** — offering amounts, names, and private chat messages.
`data/` is git-ignored and **nothing under it is ever committed** — no real church data (offering amounts, names, or private messages) lives in this repository.
