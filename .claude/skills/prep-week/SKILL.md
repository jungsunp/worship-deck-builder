---
name: prep-week
description: Read this week's band lead sheets with Claude's own vision and pre-fill the review page's worship-song lyrics — the right gasazip song, section labels (V1/C/B/Ending…) and the play order from the red marks (V/C/B, ×N, X-outs, segues) — then suggest 교회소식 fixes (bulletin typos and spacing, line breaks, shorter wording for items the build would shrink). Writes data/runs/<date>.suggest.json for review to offer behind apply buttons. Use when the user runs /prep-week <date>, or asks to read/prep the week's sheets or announcements after assemble and before review.
---

# /prep-week <date> — sheet marks → review suggestions (#209)

Run **after assemble, before review**, from the repo root (the main checkout, where `data/`
lives). `<date>` is the run date (`YYYY-MM-DD`, e.g. `2026-11-15`); with no date, use the
newest `data/runs/*.json`.

You read the sheets; `worship_deck.lyrics.suggest` does everything deterministic. **Lyric
text always comes from gasazip — never type lyrics from the image.** The only text you write
is short anchors (the lyric beside a red section letter) that the helper maps onto the
canonical lines. Never edit `data/runs/<date>.json` (review's saves replace it wholesale);
the helper writes the sidecar `data/runs/<date>.suggest.json`, and the operator applies each
song in review and saves.

**Budget:** single pass, no subagents, each sheet image read once. Aim for ~30–40k tokens for
the lyrics, plus ~5–8k for 교회소식 (step 6).

The helper is `.venv/bin/python -m worship_deck.lyrics.suggest` (written `$PY` below; spell it
out in each command, shell variables don't persist between calls).

## 1. See what assemble produced

```bash
$PY show <date>
```

This lists the inbox sheets (assemble's order) and the run's worship songs, by `ref`. For each
song it shows the gasazip `song_id`, `merged_sheets` (continuation pages assemble already
folded in), its current sections and arrangement, and the candidates for an unresolved song.

## 2. Read each sheet once (Read tool on the image)

For each sheet, note:
- **Title.** Is it a new song, a continuation page of the previous one, or only an
  intro/instrumental strip with no lyrics?
- **Red section letters** (V, V1, PC, C, B, Ending/bis…) and the first few lyric words
  printed right where each letter sits. These are your anchors.
- **The play-order line** (usually typed or written in red near the top), copied as written:
  `Intro - V1 - V1 - C - V2 - C - C`, `Cx4 - Cx2(목소리)`, `C x 3`, `--> 연결 다음곡`.
- **X-outs.** Sections crossed out are not played.
- **Instrumental notes** (전주, 간주, Intro, Outro, Interlude, "4마디"). These produce no slides.

## 3. Get the canonical lyrics

- If assemble matched the right song (title agrees with the sheet), use its `song_id`.
- Otherwise search with the sheet's real title, then take the best candidate whose lyrics
  agree with the sheet:
  ```bash
  $PY search <date> <ref> "<title>"
  ```

Then print the numbered canonical lines (`──` marks a blank stanza break):

```bash
$PY lines <song_id>
```

## 4. Write the spec — `data/runs/<date>.spec.json`

```json
{"worship_songs": [
  {"ref": 0, "song_id": "3018234", "sheets": ["003", "004"],
   "sections": [
     {"label": "V1", "at": "주의 자녀로 산다는 것은 불 가운데로"},
     {"label": "V2", "at": "주의 자녀로 산다는 것은 바다 위로"},
     {"label": "C",  "at": "때론 불 가운데 휩싸일"},
     {"label": "V3", "at": "주의 자녀로 산다는 것은 나도 그들을"},
     {"label": "V4", "at": 16},
     {"label": "C",  "at": 20}
   ],
   "arrangement": "V1 V2 Cx2 V3 V4 Cx2",
   "marks": "V1 - V2 - Cx2 - V3 - V4 - Cx2 - '보라' 연결",
   "note": "short, only if something is ambiguous", "confidence": "high"},
  {"ref": 1, "continuation_of": 0, "sheets": ["004"], "note": "곡 1의 2쪽"}
]}```

Rules:
- **One entry per run song (`ref`).** If a continuation page or intro strip became its own
  song in the run, give it `{"ref": i, "continuation_of": j, "note": …}`; review tells the
  operator to delete it. Already-merged pages (`merged_sheets` > 1) need nothing extra: list
  both sheets and join the pages' play orders in sequence.
- **`sections`**, in canonical-text order. `at` is either the anchor text from the sheet or a
  line number from `lines`; optional `end` is the section's last line (inclusive). A section
  runs until the next entry starts, so where the canonical text repeats a section (the chorus
  printed after every verse), list its label again at that point as a boundary. The first
  occurrence defines the card. Text before the first entry (credits, a skipped intro verse) is
  left out.
- **Labels** follow the operator's habits: `V1 V2 V3 …`, `PC`, `C`, `C2`, `B`, `Tag`,
  `Ending`. Define a crossed-out section only if the order still uses it.
- **`arrangement`** uses only your labels, in sheet play order. Keep ×N as written (`Cx3`; the
  helper expands it). Leave out instrumentals and X-outs, and put segues/연결 in `marks`/`note`.
  A repeated verse is the label again (`V1 V1`). Checked against 16 weeks of sent decks:
  - The typed/red play-order line is the authority. Do **not** expand the notation's own
    repeat signs (𝄆 𝄇, 1./2. endings): `V C B` with a repeat sign on C stays `V C B`. Only an
    explicit ×N (`C×2`, `Cx4`) repeats.
  - Likewise, where gasazip prints a repeat-signed section's two passes back to back with the
    **same words**, cut the card to one pass with `end`. The helper warns when a card contains
    its own first two lines again. Keep both passes when the words differ (1st/2nd endings,
    "…넘치네 (할렐루야)" then "…넘치네"), or when the sheet writes the section out twice
    instead of using a repeat sign. A half-chorus note like `C(1/2)` is still just `C`, and
    per-pass performer notes (`V(P.John / all)`, `Cx4 (한/영/영/한)`) add no plays.
  - "C Intro" / "Chorus를 Intro로" means the chorus is **sung** first: start the order with `C`.
    "간주", "Chorus반주" and a bare "Intro"/"Outro" are instrumental, with no slides.
- `marks` is the play-order line as written on the sheet (review shows it beside the
  suggestion).

## 5. Map and check

```bash
$PY apply <date> data/runs/<date>.spec.json
```

The report prints every card's lines, the expanded arrangement and any ⚠ warnings (an anchor
not found or uncertain, an unknown label, an empty order). Fix a warning by switching that
anchor to a line number from `lines`, then re-run `apply`; the sidecar is overwritten. Check
each card starts and ends where the sheet's red letters say.

## 6. 교회소식 — wording fixes

One pass over the week's announcements, after the lyrics. As with the lyrics, the helper writes the
sidecar and the operator applies. The helper is `.venv/bin/python -m worship_deck.announce_suggest`
(`$PA` below).

```bash
$PA show <date>
```

This prints every item as the slide wraps it at 80pt. `↩` marks a wrap the slide makes by itself
(it is not in the text). ⚠ marks an item the Keynote build would shrink below 80pt.

Write `data/runs/<date>.announce.json` with entries only for items that need something:

```json
{"announcements": [
  {"item": 4, "edits": [
    {"kind": "typo", "old": "1일 부터", "new": "1일부터", "why": "띄어쓰기"},
    {"kind": "typo", "old": "작정해 주세요", "new": "작성해 주세요", "why": "작정 → 작성"},
    {"kind": "typo", "old": "오후: 600", "new": "오후 6:00", "why": "시각 표기"}]},
  {"item": 7, "edits": [
    {"kind": "break", "old": "수집 / Thanksgiving Day", "new": "수집\n    Thanksgiving Day",
     "why": "제목이 / 뒤에서 넘어감"}]}
]}
```

`old` is copied from the item with just enough context to occur once in it (a line break is
`\n`); `new` replaces it. Two edits in an item can't share characters. Keep the edits small and
separate, so the operator can take one and skip another. Each edit has one kind:

- **typo**: a clear slip carried over from the bulletin. That means missing or extra spacing
  (`수료예배있습니다` → `수료예배 있습니다`; particles like 부터 attach: `1일부터`), a wrong word
  (`작정해` → `작성해`; `소속이시면` in a statement → `소속이시며`), a mistyped time or number
  (`600` → `6:00`), a stray hyphen in a phone number, or a missing final period. Leave names,
  dates, amounts, English titles and loanword spellings (싸인업, 도네이션) alone. When unsure, skip it.
- **break**: line breaks. The operator keeps a notice's prose as one paragraph: join a hard
  break inside a sentence or between its sentences. Where the topic changes (a second point,
  like thanking the previous leader), use a blank line instead. Break a title that wraps
  mid-phrase; the house style drops ` / ` and indents the continuation 4 spaces, as above. Set
  bullets (`•`, `- 시간:` lines) off from the prose before or after them with a blank line.
- **shorten**: only for ⚠ items. Cut ornamental or repeated wording: a sentence that restates
  the purpose (`특히 … 기대합니다.`), a repeated word (`보내는 … 보내기`), a redundant unit
  (`$20~30/box` → `$20~30`). Joining two short paragraphs into one also saves a line. Never cut a
  date, time, place, cost, contact or name. Aim to fit at 80pt; the report says whether it does.
- **style**: the operator's own choice, which varies week to week. It is offered but never part
  of 모두 적용. Split a prose line that mixes date and place, or date and 테마, into
  `- 시간: …` / `- 장소: …` lines, and a line listing several dates into one `•` line each.
  Move a `(문의 …)` that sits inside prose or a bullet onto its own line.

```bash
$PA apply <date> data/runs/<date>.announce.json
```

The report lists every edit and each item's build size before → after (all kinds but style).
✗ marks an edit that didn't land: fix its `old` and re-run. ⚠ marks an item still below 80pt.
Re-running replaces only the 교회소식 suggestions; the lyric ones stay.

## 7. Hand off

Tell the operator, per song: the suggested song (and whether it differs from assemble's pick),
the play order, and anything uncertain. For 교회소식, one line per item: what would change and
why. Then: open review, tap **적용** on each "Claude 제안" block, check, and **저장**. In
교회소식, **모두 적용** takes every edit except the 선택 (style) ones, which each need their own
**적용**. Nothing is applied until they do. The weekly pipeline does not depend on this skill:
without a sidecar, review works exactly as before.
