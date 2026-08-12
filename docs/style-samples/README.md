# Slide style samples (#189)

Sample slide-style options for the worship-team decision meeting: **3 lyric
lower-third options** (A/B/C) and **5 full-screen options** (1–5) across the
four full-screen sections (verse / announcements / divider / liturgy). Gates
#168's open items (palette, bar-vs-plain lower-third) and Theme authoring
(#170).

Content mimics the **actual 2026-07-05 service** (`data/runs/2026-07-05.json`
+ `master.key` slide texts): 다시 한 번 chorus, 요 1:9-12 call-to-worship,
real bulletin announcements (member names scrubbed — these PNGs are
committed), 찬 283장 offering divider, and the current deck's 사도신경 text at
its real 7-line density. The camera backgrounds are frames from our own
2026-06-28 live stream (already public on YouTube).

## Lyric lower-third (A/B/C)

| Option | Modeled on | Treatment |
|---|---|---|
| **A — 검정 스트립** | Hillsong ref (`ref-hillsong.png`) | bold white on per-line text-hugging black strips |
| **B — 플레인** | IN2 NY / KCPC / 남가주사랑의교회 | white + shadow over camera, subtle bottom scrim, no box |
| **C — 블러 박스** | current NPC navy banner, modernized | blurred translucent navy box |

## Full-screen (1–5)

Chosen to balance modern and classic — the congregation is multi-generation
and the church's own branding (npcwheeling.com) is navy/white,
modern-traditional. The earlier black+red set was dropped as too modern.
All options stay white-on-dark (confirmed decision).

| Option | Palette | Font (placeholder) | Character |
|---|---|---|---|
| **1 — 클래식 세리프** | deep navy + ivory + gold rules | Noto Serif KR | classic, hymnal/예식서 |
| **2 — 차콜 골드** | warm charcoal radial + gold | SUIT | modern-classic, elegant |
| **3 — 네이비 프레임** | navy + blurred photo + frame box | Noto Sans KR | closest to current deck |
| **4 — 로열 블루** | Bethel-Irvine-style royal blue gradient | Pretendard | modern, church-blue |
| **5 — 버건디 클래식** | deep burgundy + cream | Noto Serif KR | classic, traditional church color |

Fonts are placeholders per #189's out-of-scope note — the typeface decision is
a separate #168 line item (the serif-vs-sans reaction is the useful signal).

Reference research: `docs/slide-style-references.md` (Hillsong/IN2/KCPC/Kairos)
plus fresh 2026-07-05 replay frames from 남가주사랑의교회 (KO-over-EN white
text, no box — a fourth no-box bilingual precedent) and 베델교회 어바인 (royal
blue stage brand → option 4). The downloaded free `.proTheme`s (in
`data/propresenter-trial/themes/`) decode as `rv.data.Template.Document` and
informed text sizes and scripture-bar alpha; the ProPresenter ProContent themes
(*Shapes*, *Box Blur*, *One Size Fits All*) turned out to be premium-only, so
those looks are modeled on their public previews. The free downloads we do
have are the CMG pack and *TheCove* (a full section set — the structural
reference for Theme authoring in #170).

## Files

- `{a,b,c}-{lyric-ko,lyric-bi}.png` + `f{1..5}-{verse,announce,divider,liturgy}.png`
  — 26 sample slides, 1920×1080, option badge top-right.
- `compare.html` — side-by-side comparison page with the decision checklist.
  Open directly in a browser; print for handouts.

## Regenerating

```bash
.venv/bin/python scripts/render_style_samples.py        # PNGs (+ meeting label slides)
.venv/bin/python scripts/build_style_sample_deck_pro.py # ProPresenter deck (primary)
.venv/bin/python scripts/build_style_sample_deck.py     # Keynote deck (fallback)
```

The `.pro` builder clones document scaffolding from a known-valid local 21.4
presentation and synthesizes full-bleed image slides (element anatomy from the
decoded TheCove theme), one ProPresenter group per section. Because the slides
are baked PNGs, styles can't be tweaked live in ProPresenter during the
meeting — live-editable native text slides need the #172 text-element
generation (planned follow-up for the finalist options). The `.pro` was
authored against PP 21.4; whether the church's 18.4 opens it is the open #191
question — trying it there doubles as that verification, and the Keynote deck
is the meeting fallback if it doesn't.

Inputs live in git-ignored `data/style-samples/`: `fonts/` (Pretendard, SUIT,
Noto Sans KR, Noto Serif KR — free downloads), `bg/` (frames extracted from
`data/propresenter-trial/band-loop.mp4` and the YouTube replay via
yt-dlp/ffmpeg). The deck builders write `data/style-samples/style-samples.pro`
/ `.key` — 33 slides grouped by section (label, then that section's options
back-to-back) so the group compares like-for-like.
