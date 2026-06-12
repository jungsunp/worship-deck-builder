# UI revamp spike (#123): research, design proposal, strategy, phased plan

Spike deliverable for #123. The web UI grew feature-by-feature into two inline-HTML pages
with browser-default styling; this doc researches best-in-class referents, proposes a
redesign, recommends an implementation strategy, and drafts the phased issues.

Constraints (from #123): iPhone over Tailscale is the primary device; Korean text; a single
operator on a weekly cadence; FastAPI backend stays; redesign lands incrementally — a Sunday
build can never be blocked by it.

---

## 1. Research: reference apps and what to borrow

### 1.1 Planning Center Services — the order-of-service is the spine

The closest domain match: weekly service-prep for churches, mobile-first. Their 2024 plan-view
redesign ([blog post](https://www.planningcenter.com/blog/2024/04/services-app-redesigned-plans-page-for-smoother-navigation))
is directly instructive:

- **They replaced row → sub-page navigation with tabs/sections in one view** — users hated
  bouncing through sub-pages and back buttons. Our review page already got this right
  (everything inline in worship order); the redesign should *keep* that and add a way to jump
  between sections instead of scrolling blind.
- **The order of service is the primary navigation structure.** Our review page renders
  `worship_order` rows top-to-bottom — same instinct. Borrow: make each row a collapsible
  **section card** with a status badge (✓ ready / ✎ edited / ⚠ missing), so the operator sees
  at a glance what still needs attention before Generate.
- **General actions live in a persistent header/footer; section actions live in the section.**
  Borrow: Save/Generate belong in a sticky bottom bar, not at the end of a long scroll.

### 1.2 Vercel deployments — a run is a first-class object with visible steps

([Deployments docs](https://vercel.com/docs/deployments),
[managing deployments](https://vercel.com/docs/deployments/managing-deployments).)
Our assemble → review → build maps 1:1 onto their build → preview → promote:

- **Every run has a status page**: current step, what triggered it, errors expandable in
  place, and history of previous runs. Borrow: a **status stepper** (업로드 → Assemble →
  검토 → 빌드) rendered identically on home and review, fed by the existing
  `/assemble/{date}/status` and `/runs/{date}/build/status` polls — instead of today's
  one-line `textContent` status div.
- **Errors are first-class, not an afterthought**: failed step highlighted, log/detail
  expandable. Borrow: render assemble *warnings* (missing slots, hymn download failed —
  already returned in the status JSON) as a visible warning card, not a `⚠` line that
  scrolls away.
- **History is cheap and reassuring**: a list of past runs with dates and outcomes. Our
  `/runs` JSON already exists; give it a real surface (also the natural home for #118's
  timings and #102's PDF preview link).

### 1.3 Upload UX (Uploadcare / file-upload pattern literature) — slots as a checklist

([Uploadcare UX best practices](https://uploadcare.com/blog/file-uploader-ux-best-practices/),
[Eleken file-upload UI examples](https://www.eleken.co/blog-posts/file-upload-ui).)
The #109 slot model (dedicated slot per source, auto-upload on select, replace semantics) is
already the right pattern — what's missing is *state communication*:

- **A fixed set of required inputs is a checklist, not a form.** Borrow: render the four
  slots as checklist cards with explicit states — empty (⬜ + upload affordance), filled
  (✓ + filename/size/preview-line + replace/delete), error (file rejected, with the reason).
  The Assemble CTA shows readiness ("Assemble — 3/4 준비") rather than letting a half-empty
  inbox assemble silently into warnings.
- **Mobile pickers need big targets**: the whole card tappable, ≥44px, not a bare
  `<input type=file>` line.
- **Clear immediate feedback per file** — we have ✓/filename rows since #109; keep them,
  promote upload errors from a shared status line into the slot itself.

### 1.4 Wildcard: thumb-zone ergonomics — sticky bottom action bar

(NN/g-derived thumb-zone research:
[Parachute Design thumb-zone guide](https://parachutedesign.ca/blog/thumb-zone-ux/),
[UX Movement on mobile CTA placement](https://uxmovement.com/mobile/optimal-placement-for-mobile-call-to-action-buttons/).)
~49% of users operate one-handed; the bottom third of the screen is the natural thumb zone.

- **Primary action sticky at the bottom**, padded above the iOS home indicator
  (`env(safe-area-inset-bottom)`), full-width, ≥44px tall. Today Assemble/Save/Generate sit
  mid-document and scroll away — on the review page Generate is below every editor.
- **One primary action per screen state**: Home → Assemble; Review → Generate (with Save as
  the secondary in the same bar). Disabled states explain themselves ("주보 없음").

Korean-readability specifics (applies everywhere):

- `word-break: keep-all` — the single highest-impact CSS line for Korean prose; prevents
  mid-word line breaks in labels, hints, and passage text.
- Form inputs at `font-size ≥ 16px` — iOS Safari auto-zooms on focus below 16px, which is
  exactly the disorienting jump the operator hits in the lyric textareas today (1rem = 16px
  holds only until any style change shrinks it; make it an explicit token).
- Font stack: `-apple-system, "Apple SD Gothic Neo", "Noto Sans KR", sans-serif` (iOS resolves
  Korean through Apple SD Gothic Neo already; the explicit entries cover non-Apple browsers).

---

## 2. Design proposal

### 2.1 Principles

1. **Checklist over form** — the operator's Sunday question is "what's still missing?", every
   screen answers it at a glance.
2. **One status model everywhere** — a single 4-step pipeline stepper (업로드 → Assemble →
   검토 → 빌드) on both pages, fed by existing status endpoints.
3. **Thumb-zone primary action** — sticky bottom bar, one primary CTA per page.
4. **Korean-first text rendering** — `word-break: keep-all`, ≥16px inputs, generous line-height.
5. **No backend changes** — the redesign consumes exactly the existing JSON endpoints.

### 2.2 Page inventory

| Page | Route | Today | Redesign |
|---|---|---|---|
| Home ("이번 주") | `/` | upload slots + assemble + status line + runs list | readiness checklist + stepper + sticky Assemble; runs list demoted to a "지난 실행" link section |
| Review | `/review/{date}` | worship-order rows with inline editors, Save/Generate at bottom | same spine, sections become collapsible status-badged cards + section-jump chips + sticky Save/Generate bar |
| Runs / history | (JSON only: `/runs`) | links on home page | small page: past runs, outcome, link to review; future home of #118 timings + #102 PDF link |

Endpoint mapping (all existing, unchanged): `/inbox`, `/upload/{kind}`, `/inbox/choir`,
`/inbox/{name}` DELETE, `/assemble` (+ confirm flow), `/assemble/{date}/status`, `/runs`,
`/runs/{date}` GET/PUT, `/runs/{date}/hymn[/{name}]`, `/runs/{date}/build[/status]`.

### 2.3 Wireframes (iPhone width)

**Home — readiness checklist:**

```
┌─────────────────────────────────┐
│ Worship Deck                    │
│ ○ 업로드 ─ ○ Assemble ─ ○ 검토 ─ ○ 빌드   ← stepper (state-colored)
├─────────────────────────────────┤
│ 이번 주 준비물            3 / 4 │
│ ┌─────────────────────────────┐ │
│ │ ✓ 주보 (PDF)                │ │  ← filled card: tap = replace
│ │   bulletin.pdf · 412 KB   ✕ │ │
│ ├─────────────────────────────┤ │
│ │ ✓ 찬양 악보 · 3장           │ │
│ │   sheet-01 · sheet-02 · …   │ │
│ │   [＋ 추가]                 │ │
│ ├─────────────────────────────┤ │
│ │ ⬜ 고백의 찬양 악보          │ │  ← empty card: whole card =
│ │   탭하여 업로드             │ │     file picker, ≥44px
│ ├─────────────────────────────┤ │
│ │ ✓ 성가대 가사 · 저장됨      │ │
│ │   "주 하나님 지으신 모든…"  │ │  ← preview line; tap to expand
│ └─────────────────────────────┘ │     the textarea in place
│                                 │
│ ⚠ 기타 파일 1개 — 슬롯 미인식   │  ← only when present
│                                 │
│ 지난 실행                       │
│   6월 8일 — 검토 →              │
├─────────────────────────────────┤
│ ┃  Assemble  (3/4 준비)       ┃ │  ← sticky; readiness inline;
└─────────────────────────────────┘     disabled w/ reason if no 주보
```

**Home — assemble running (same page, stepper + status card take over):**

```
│ ● 업로드 ─ ◐ Assemble ─ ○ 검토 ─ ○ 빌드 │
│ ┌─────────────────────────────┐ │
│ │ ◐ Assembling… (verses)      │ │  ← current step from status JSON
│ │ ⚠ 고백의 찬양 악보 없음      │ │  ← warnings as visible card
│ └─────────────────────────────┘ │
│ … checklist below …             │
│ ┃  검토 화면으로 →            ┃ │  ← CTA flips when done
```

**Review — section cards + jump chips + sticky bar:**

```
┌─────────────────────────────────┐
│ ← 홈   6월 15일 검토            │
│ [찬양][부름][고백][성가대][봉헌] │  ← sticky horizontal chips,
│ [소식][말씀]                    │     scroll-to-section
├─────────────────────────────────┤
│ ▼ 찬양  마라나타 · 3곡        ✎ │  ← expanded card, edited badge
│ ┌─────────────────────────────┐ │
│ │ 1 주를 향한 나의 사랑   ▲ ▼ │ │
│ │ ┌─────────────────────────┐ │ │
│ │ │ lyric editor —          │ │ │  ← auto-grow textarea (#112):
│ │ │ grows with content,     │ │ │     whole song visible, no
│ │ │ no inner scroll         │ │ │     manual resize
│ │ └─────────────────────────┘ │ │
│ └─────────────────────────────┘ │
│ ▶ 예배의 부름  시 100:1-5     ✓ │  ← collapsed read-only card
│ ▶ 고백의 찬양  주께 가오니    ✓ │
│ ▶ 성가대  주 하나님…         ✎ │
│ ▼ 봉헌  545장 · 6/8 선택      ✓ │
│ │ [번호] [제목]               │ │
│ │ ▦ ▦ ▦ ▦ ▦ ▦ ▦ ▦  (thumb    │ │  ← keep/drop grid as today
│ │    grid, tap to toggle)     │ │
│ ▶ 교회소식  5건               ✓ │
│ ▶ 말씀  요 3:16-21           ✓ │
├─────────────────────────────────┤
│ ┃ 저장 ✓ │  ▶ 덱 생성        ┃ │  ← sticky; save state inline;
└─────────────────────────────────┘     building → stepper/progress
```

**Status stepper component (shared):** four dots+labels; states empty ○ / active ◐ (pulsing) /
done ● / error ✕ (red, tap to expand the error/warning card). Driven by the same polling JS
that exists today.

### 2.4 Component & style approach

A single shared stylesheet built on CSS custom properties — no framework, no build step:

- **Tokens:** brand colors (keep the current blue `#2563eb` / green `#16a34a` / purple
  `#7c3aed` family — they already encode upload/assemble/build), gray scale, spacing scale
  (4/8/12/16/24), radius (8px), type scale (16px base, 1.3rem h1), `--safe-bottom:
  env(safe-area-inset-bottom)`.
- **Components (CSS classes + a few small JS helpers):** `card` (slot/section), `checklist
  row` (state variants), `chips` (section nav), `stepper`, `stickybar`, `badge` (✓/✎/⚠),
  auto-grow textarea (one 3-line JS helper: set height to scrollHeight on input).
- **Global text rules:** `word-break: keep-all`, `line-height: 1.5`, inputs/textarea 16px.
- Dark mode, animation polish, and desktop layouts are explicit **non-goals** (single
  operator, iPhone, Sunday morning).

---

## 3. Implementation strategy recommendation

**Recommendation: (b) move pages to static files served by FastAPI — keep the template-free,
JSON + fetch architecture, drop only the "inline Python strings" part.**

| Option | Verdict |
|---|---|
| (a) keep inline strings, extract shared CSS string | Smallest diff, but the redesign ~doubles the markup/JS and editing HTML inside Python strings (escaped `\n`, no syntax highlighting/linting) is already the bottleneck; `app.py` is at 967 lines and would pass 1,500. |
| **(b) static `web/static/` HTML/CSS/JS, served via `FileResponse`/`StaticFiles`** | **Chosen.** Zero new dependencies, zero build step, same template-free + fetch-JS model, real editor support for HTML/CSS/JS, `app.py` shrinks to pure API. Existing tests already assert on *served* HTML (`client.get("/").text`, e.g. `tests/test_web.py:174,655,701`) so they keep passing unchanged. |
| (c) htmx | Solves server-driven partial updates — but our dynamic state (medley reorder, hymn keep/drop grid, debounced choir autosave) is client-state-driven, which htmx handles awkwardly. Adds a vendored dependency to replace ~150 lines of working JS. No. |
| (d) SPA / build tooling | npm + build step on the church Mac for a 3-page single-operator tool. No. |

Mechanics: `/` and `/review/{date}` return `FileResponse` of `web/static/index.html` /
`review.html` (review already reads the date from `location.pathname`, so one file serves all
dates); shared `app.css` + `app.js` mounted via `StaticFiles`. Package the directory so
`pip install -e .` keeps working (include `web/static/*` as package data).

**Proposed CLAUDE.md wording change** (replaces the current "intentionally template-free"
paragraph):

> The web app (`web/app.py`) is API-only: pages are static HTML/CSS/JS files under
> `web/static/` served by FastAPI (no template engine — `review.html` reads its date from
> `location.pathname`); dynamic content uses small JSON endpoints + `fetch`-based JS, with
> shared design tokens in `web/static/app.css`. Match this — don't add Jinja2 or a JS build
> step.

**Migration cost:** Phase 0 below is the whole migration — one PR, mostly mechanical
(cut the two HTML strings into files, unescape `\\n` → `\n`, add two `FileResponse` routes +
one `StaticFiles` mount, package-data entry). Verified by diffing served bytes before/after.

**Concurrent-session risk:** `web/app.py` is touched by many open issues (#112, #114, #116,
#118, #102). Phase 0 moves ~450 lines out of it — land it in a quiet window, not alongside
another session editing the HTML strings. Later phases touch only `web/static/`, which
*reduces* future collision risk in `app.py`.

---

## 4. Phased implementation plan (issue drafts — not yet filed)

Each phase is one independently shippable PR; production keeps working after every phase
(weekly build never blocked). Rollback = revert one PR.

**Phase 0 — Extract pages to `web/static/`, no visual change.**
Move `_INDEX_HTML`/`_REVIEW_HTML` into `web/static/index.html` + `review.html`, extract the
common CSS into `app.css` with the design tokens (§2.4), serve via `FileResponse` +
`StaticFiles`, add package-data. Acceptance: served HTML functionally identical (tests
`test_web.py` pass unedited), pages work from the phone. Update the CLAUDE.md paragraph.

**Phase 1 — Home as a readiness checklist + stepper + sticky Assemble.**
Wireframe §2.3-Home: slot checklist cards with empty/filled/error states (whole-card tap
targets), readiness count in the sticky CTA, stepper + warning card replacing the status
line, runs list demoted to "지난 실행". Existing endpoints only. Acceptance: all current
home-page behaviors (slot upload/replace/delete, choir autosave, re-assemble confirm flow,
status poll → review link) work in the new layout.

**Phase 2 — Review as section cards + jump chips + sticky Save/Generate.**
Wireframe §2.3-Review: collapsible status-badged section cards, sticky chips nav, sticky
bottom bar, auto-grow lyric textareas (**closes #112**). Hymn grid and reorder controls keep
today's logic. Acceptance: edit → save → re-load round-trip identical to today; Generate flow
incl. build poll unchanged.

**Phase 3 — Runs/history page + richer build status.**
Small `/runs` HTML page: past runs, outcome, review links; build-status area structured to
host #118's timings and #102's PDF-preview link when those land (this phase builds the
surface, not those features). Acceptance: navigable from home; no backend changes.

Synergies: #112 is absorbed by Phase 2; #118 and #102 get their natural UI home in Phase 3;
#116 (announcement bullets) is content-shaping, orthogonal to this revamp.

---

## 5. Spike status

- [x] Research writeup (§1) — deliverable 1
- [x] Design proposal: page inventory, wireframes, component approach (§2) — deliverable 2
- [x] Implementation strategy + CLAUDE.md change + migration cost (§3) — deliverable 3
- [x] Phased plan drafted (§4) — deliverable 4 (**issues not yet filed** — file Phase 0–3 as
  GitHub issues and post the summary comment on #123 after this doc is reviewed)
