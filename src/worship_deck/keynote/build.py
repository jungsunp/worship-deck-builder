"""Build the draft deck by driving Keynote.app via AppleScript/JXA.

Requires a Mac that is powered on and logged in. Starting from the template deck, this
duplicates section slides to fit the week's content, places the rendered PNGs and the
existing hymn image slides in order, and saves data/drafts/draft-YYYY-MM-DD.key plus a
PDF preview for phone review. AppleScript sources live in ./applescript/.
"""

from __future__ import annotations

import math
import subprocess
import time
from pathlib import Path

from worship_deck.bible.verses import Verse, english_ref, verse_labels
from worship_deck.lyrics.transcribe import Song, chunk
from worship_deck.parse.bulletin import ServiceData

_SAVE_DRAFT = Path(__file__).parent / "applescript" / "save_draft.applescript"
_FINALIZE = Path(__file__).parent / "applescript" / "finalize.applescript"
_DUPLICATE_SLIDE = Path(__file__).parent / "applescript" / "duplicate_slide.applescript"
_DUPLICATE_BLOCK = Path(__file__).parent / "applescript" / "duplicate_block.applescript"
_SET_DATE_SLIDES = Path(__file__).parent / "applescript" / "set_date_slides.applescript"
_SET_VERSE_SLIDE = Path(__file__).parent / "applescript" / "set_verse_slide.applescript"
_READ_VERSE_BOXES = Path(__file__).parent / "applescript" / "read_verse_boxes.applescript"
_DELETE_SLIDES = Path(__file__).parent / "applescript" / "delete_slides.applescript"
_SET_SLIDE_TEXT = Path(__file__).parent / "applescript" / "set_slide_text.applescript"
_SET_ANNOUNCEMENT_SLIDE = Path(__file__).parent / "applescript" / "set_announcement_slide.applescript"
_SET_CHOIR_TITLE = Path(__file__).parent / "applescript" / "set_choir_title.applescript"
_SET_SERMON_TITLE = Path(__file__).parent / "applescript" / "set_sermon_title.applescript"
_SET_OFFERING_HYMN_TITLE = (
    Path(__file__).parent / "applescript" / "set_offering_hymn_title.applescript"
)
_PLACE_IMAGE = Path(__file__).parent / "applescript" / "place_image.applescript"
_HYMN_IMAGE_BLOCK = Path(__file__).parent / "applescript" / "hymn_image_block.applescript"
_READ_TITLE_BOX = Path(__file__).parent / "applescript" / "read_title_box.applescript"
_SET_CTW_REF = Path(__file__).parent / "applescript" / "set_ctw_ref.applescript"
_SET_SERMON_REF = Path(__file__).parent / "applescript" / "set_sermon_ref.applescript"

# --- verse-slide layout model (calibrated against master.key renders) ---------------------
# Keynote exposes no autoshrink/effective-size info via AppleScript, so we estimate how much
# text fits a verse box at a readable font and paginate to keep text from shrinking below it.
_LINE_H = 1.2        # line height as a multiple of font size
_CHAR_W_KO = 1.0     # avg glyph advance / font size — full-width Hangul
_CHAR_W_EN = 0.5     # avg glyph advance / font size — proportional Latin
_MIN_FONT_KO = 60    # readability floor (pt); calibrated so pagination matches master.key's
_MIN_FONT_EN = 44    # slide counts (시 133:1-3 → 1 slide, 눅 22:14-24 → 4) at master's effective sizes

# --- sermon-title fit model (#106 follow-up) ----------------------------------------------
# The standalone 말씀 title box auto-grows to its content (no word-wrap/autoshrink via
# AppleScript), so a long title at the designed font overflows the decorative frame around it
# (e.g. "왜 그럼 그 때는 가만히 계셨을까?"). We wrap it ourselves and pick the LARGEST font that fits
# the frame, so the title stays the dominant element (bigger than the gold scripture ref) —
# matching the church's hand-built decks.
_TITLE_CHAR_W_KO = 0.83  # Hangul title advance / font: calibrated to master.key's title box
                         # ("이를 행하여 / 나를 기념하라" = 7-char lines at 130pt in a 758pt box)
_MIN_FONT_TITLE = 70   # readability floor (pt); options at/above it are preferred when wrapping
_MAX_TITLE_LINES = 4   # cap on wrapped title lines considered


def _run_osascript(script: Path, *args: str) -> str:
    """Run an AppleScript file via osascript, returning its stdout.

    Raises:
        RuntimeError: if `osascript` is missing (not macOS) or the script fails.
    """
    try:
        result = subprocess.run(
            ["osascript", str(script), *args],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError as e:  # `osascript` only exists on macOS
        raise RuntimeError("`osascript` not found — Keynote automation needs macOS.") from e
    if result.returncode != 0:
        raise RuntimeError(f"Keynote script {script.name} failed: {result.stderr.strip()}")
    return result.stdout


def _ensure_keynote_ready(settle: int = 8, tries: int = 20) -> None:
    """Launch Keynote, wait for scripting, and confirm it has ZERO open documents.

    A document left open by a prior run (e.g. an eyeball draft) makes the next `open` return
    `missing value` (-1700) and can wedge the save (-609/-1712). So before building we close
    every document and poll the count to 0, retrying. Never force-quit to reset — that leaves
    the scripting bridge in a -609 ("connection is invalid") state; a clean launch + settle +
    doc-clearing is the reliable reset. Mirrors the eyeball-deck helper's `ensure_keynote_ready`.
    """
    subprocess.run(["open", "-a", "Keynote"], check=False)
    time.sleep(settle)
    for _ in range(tries):
        if subprocess.run(
            ["osascript", "-e", 'tell application "Keynote" to get name'],
            capture_output=True, text=True,
        ).returncode == 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError("Keynote did not become responsive — launch it manually, then retry.")
    for _ in range(tries):
        subprocess.run(
            ["osascript", "-e", 'tell application "Keynote" to close every document saving no'],
            check=False,
        )
        r = subprocess.run(
            ["osascript", "-e", 'tell application "Keynote" to count documents'],
            capture_output=True, text=True,
        )
        if r.returncode == 0 and r.stdout.strip() == "0":
            return
        time.sleep(1)
    raise RuntimeError(
        "Keynote still has documents open after repeated close attempts — it is likely wedged "
        "(a stuck save or modal dialog). Quit Keynote manually (not force-quit during a save), "
        "relaunch, and retry."
    )


def save_draft(template_key: str, out_key: str) -> str:
    """Open the template deck and save a copy to out_key, returning out_key.

    The first Keynote primitive (#20): proves we can drive Keynote over AppleScript.
    Save-As leaves the template untouched. Later issues (#21, #13–16) extend this plumbing
    to duplicate slides and set native text.

    Open-once/save-once (#117): this writes a pristine copy to out_key, then CLOSES the template
    and reopens the copy so the open `front document` is bound to the DRAFT, not the template.
    Every later primitive mutates that open document in place (no per-call open/save), and
    `finalize_draft` saves it once at the end of build(). Binding the open doc to the draft is the
    safety invariant: if a fill crashes before finalize, macOS autosave writes the open doc to
    disk — with it bound to the draft that hits the draft, but the old template-bound behavior
    silently corrupted master.key on every crashed build (#98 fallout). Callers must still run
    `_ensure_keynote_ready()` first (zero open docs → front document is unambiguously this draft)
    and `finalize_draft(out_key)` last.

    Raises:
        RuntimeError: if `osascript` is missing (not macOS) or the Keynote save fails.
    """
    template = str(Path(template_key).expanduser())
    out = str(Path(out_key).expanduser())
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    _run_osascript(_SAVE_DRAFT, template, out)
    return out_key


def finalize_draft(out_key: str) -> str:
    """Save the open draft once, at the end of build() (#117), returning out_key.

    The mutating/reading primitives no longer open/save the deck per call — they edit the open
    `front document` opened by `save_draft` — so this single save persists all of the build's
    edits (~55 disk cycles collapse to ~2). `save_draft` reopened the draft copy, so the open
    document is bound to the draft, so finalize.applescript does a plain in-place `save front
    document` (not `save … in out_key`, which would desync autosave and trigger a "changed by
    another application" warning on the still-open draft). out_key is passed for logging only —
    the script ignores it. The draft is left open; the web app's post-build `open path` focuses it.

    Raises:
        RuntimeError: if `osascript` is missing (not macOS) or the Keynote save fails.
    """
    _run_osascript(_FINALIZE, str(Path(out_key).expanduser()))
    return out_key


def duplicate_slide(key_path: str, slide_index: int, count: int) -> int:
    """Duplicate the 1-based slide at slide_index `count` times, in place.

    The second Keynote primitive (#21): expands a one-slide section template into the
    week's lyric/announcement slides (#15/#16 then fill each copy's native text). Copies
    land contiguously after the source slide. Returns the resulting total slide count.

    Raises:
        RuntimeError: if `osascript` is missing (not macOS) or the Keynote script fails.
    """
    key = str(Path(key_path).expanduser())
    out = _run_osascript(_DUPLICATE_SLIDE, key, str(slide_index), str(count))
    return int(out.strip())


def duplicate_block(
    key_path: str, src_start: int, src_len: int, dest_after: int, times: int
) -> int:
    """Duplicate the contiguous block [src_start, src_start+src_len) to after dest_after.

    `duplicate_slide` only places copies right after their source, which interleaves when a
    multi-slide block is replicated. This copies the whole block (in order) to after
    `dest_after`, `times` times — used to fan a single worship-song unit (blank + title +
    lyric) into one per medley song (#86). The source block MUST lie entirely before
    `dest_after` so its indices stay stable while copies are inserted. Returns the new total
    slide count.

    Raises:
        RuntimeError: if `osascript` is missing (not macOS) or the Keynote script fails.
    """
    key = str(Path(key_path).expanduser())
    out = _run_osascript(
        _DUPLICATE_BLOCK, key, str(src_start), str(src_len), str(dest_after), str(times)
    )
    return int(out.strip())


def set_date_slides(key_path: str, date: str, title: str, ref: str) -> int:
    """Set the weekly date / sermon title / verse ref on the deck's date slides, in place.

    Detects date slides generically (any on-canvas text item bearing 년/월); off-canvas
    leftover items are ignored. Intro slides get date + title + ref (title and ref are the
    two paragraphs of one text item); ending slides keep their closing wording and take only
    the new date. `ref` includes brackets, e.g. "[창 1:1-5]"; `date` is pre-formatted Korean,
    e.g. "2026년 6월 7일". Returns the number of date slides updated.

    Raises:
        RuntimeError: if `osascript` is missing (not macOS) or the Keynote script fails.
    """
    key = str(Path(key_path).expanduser())
    out = _run_osascript(_SET_DATE_SLIDES, key, date, title, ref)
    return int(out.strip())


def _verse_lines(text: str, box_w: int, font: int, char_w: float) -> int:
    """How many wrapped lines `"N. " + text` takes in a box `box_w` wide at `font` pt."""
    chars_per_line = max(1, int(box_w / (font * char_w)))
    return max(1, math.ceil(len(text) / chars_per_line))


def _fit_lines(box_h: int, font: int) -> int:
    """How many lines of `font` pt fit in a box `box_h` tall."""
    return max(1, int(box_h / (font * _LINE_H)))


def _wrap_balanced(text: str, lines: int) -> list[str]:
    """Greedily pack `text`'s space-separated words into at most `lines` roughly equal lines.

    Lines break only at spaces; a per-line target of len(text)/lines keeps them balanced. A
    single word (no spaces) cannot be split, so it is returned as one line. Returns fewer than
    `lines` entries when there aren't enough words to fill them.
    """
    words = text.split()
    if lines <= 1 or len(words) <= 1:
        return [text.strip()] if words else []
    target = len(text) / lines
    out: list[str] = []
    cur = ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > target and len(out) < lines - 1:
            out.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}" if cur else w
    if cur:
        out.append(cur)
    return out


def _fit_title(text: str, box_w: int, box_h: int, base_font: int) -> tuple[str, int]:
    """Size a sermon title to a box_w×box_h box: return (text with \\n breaks, font pt).

    Keynote can't word-wrap or autoshrink via AppleScript, so we do both: try 1.._MAX_TITLE_LINES
    lines, balance-wrapping each way, and size each option by what fits the box width (longest
    line) and height (line count). Pick the LARGEST font (ties → fewest lines) so the title stays
    prominent; restrict to options at/above _MIN_FONT_TITLE when any qualify. The font is capped at
    the template's base font so short titles are never enlarged. Hangul advance is _TITLE_CHAR_W_KO.
    """
    options: list[tuple[int, int, list[str]]] = []  # (line_count, font, lines)
    for n in range(1, _MAX_TITLE_LINES + 1):
        wrapped = _wrap_balanced(text, n)
        longest = max((len(ln) for ln in wrapped), default=1)
        font = int(
            min(base_font, box_w / (longest * _TITLE_CHAR_W_KO), box_h / (len(wrapped) * _LINE_H))
        )
        options.append((len(wrapped), font, wrapped))
    pool = [o for o in options if o[1] >= _MIN_FONT_TITLE] or options
    line_count, font, lines = max(pool, key=lambda o: (o[1], -o[0]))
    return "\n".join(lines), font


def _chunk_verses(
    verses: list[Verse],
    *,
    ko_box: tuple[int, int],
    en_box: tuple[int, int],
    ko_min_font: int = _MIN_FONT_KO,
    en_min_font: int = _MIN_FONT_EN,
) -> list[list[Verse]]:
    """Group consecutive verses so each slide's text stays readable in both languages.

    For each body box (width, height) and its readability floor, estimate how many wrapped
    lines fit; a verse starts a new slide when adding it would exceed EITHER language's line
    budget (verses don't share a line). A verse that overflows on its own still gets its own
    slide. This trades extra slides for never shrinking below the floor — the user's intent.
    """
    ko_w, ko_h = ko_box
    en_w, en_h = en_box
    ko_budget = _fit_lines(ko_h, ko_min_font)
    en_budget = _fit_lines(en_h, en_min_font)

    chunks: list[list[Verse]] = []
    current: list[Verse] = []
    ko_used = en_used = 0
    for v in verses:
        ko_need = _verse_lines(f"{v.number}. {v.korean}", ko_w, ko_min_font, _CHAR_W_KO)
        en_need = _verse_lines(f"{v.number}. {v.english}", en_w, en_min_font, _CHAR_W_EN)
        if current and (ko_used + ko_need > ko_budget or en_used + en_need > en_budget):
            chunks.append(current)
            current, ko_used, en_used = [], 0, 0
        current.append(v)
        ko_used += ko_need
        en_used += en_need
    if current:
        chunks.append(current)
    return chunks


def read_verse_boxes(key_path: str, slide_index: int) -> tuple[tuple[int, int], tuple[int, int]]:
    """Return ((ko_w, ko_h), (en_w, en_h)) for the verse-body boxes on a slide (#14).

    Raises:
        RuntimeError: if `osascript` is missing (not macOS) or the Keynote script fails.
    """
    key = str(Path(key_path).expanduser())
    out = _run_osascript(_READ_VERSE_BOXES, key, str(slide_index))
    ko_line, en_line = out.strip().splitlines()
    ko_w, ko_h = (int(x) for x in ko_line.split())
    en_w, en_h = (int(x) for x in en_line.split())
    return (ko_w, ko_h), (en_w, en_h)


def read_title_box(key_path: str, slide_index: int) -> tuple[int, int, int]:
    """Return (width, height, font_pt) of the sermon-title box on a slide (#106 follow-up).

    The title box is the on-canvas text item that is NOT the bracketed scripture-ref box; its
    geometry + base font drive _fit_title's wrap/shrink so the title fits without overflowing.

    Raises:
        RuntimeError: if `osascript` is missing (not macOS) or the Keynote script fails.
    """
    key = str(Path(key_path).expanduser())
    out = _run_osascript(_READ_TITLE_BOX, key, str(slide_index))
    w, h, font = (int(float(x)) for x in out.strip().split())
    return w, h, font


def delete_slides(key_path: str, start_index: int, count: int) -> int:
    """Delete `count` consecutive slides starting at 1-based start_index. Returns new total.

    Raises:
        RuntimeError: if `osascript` is missing (not macOS) or the Keynote script fails.
    """
    key = str(Path(key_path).expanduser())
    out = _run_osascript(_DELETE_SLIDES, key, str(start_index), str(count))
    return int(out.strip())


def set_verse_slide(
    key_path: str,
    slide_index: int,
    kr_label: str,
    kr_text: str,
    en_label: str,
    en_text: str,
) -> str:
    """Set the four on-canvas text items on one verse slide (#14), in place.

    A verse slide carries a 개역한글 label + body and an ESV label + body; off-canvas leftover
    items are ignored. Items are classified by content (개역한글/ESV) and y-position (Korean
    above English), never by index, since the order varies across slides. Bodies are
    newline-joined verse text. Returns "ok".

    Raises:
        RuntimeError: if `osascript` is missing (not macOS) or the Keynote script fails.
    """
    key = str(Path(key_path).expanduser())
    out = _run_osascript(
        _SET_VERSE_SLIDE, key, str(slide_index), kr_label, kr_text, en_label, en_text
    )
    return out.strip()


def fill_verse_slides(
    key_path: str,
    start_index: int,
    kr_label: str,
    en_label: str,
    verses: list[Verse],
    *,
    existing_count: int = 1,
    ko_min_font: int = _MIN_FONT_KO,
    en_min_font: int = _MIN_FONT_EN,
) -> int:
    """Fill a verse section starting at start_index, paginating to stay readable (#14).

    Reads the section's body-box geometry, chunks `verses` so neither language shrinks below
    its readability floor (overflow spills to more slides), resizes the section from its
    template `existing_count` slides to the chunk count (trimming surplus or duplicating the
    first slide), then fills each. Every slide shows the same full-passage label (matching the
    deck). Returns the number of slides used.

    Note: resizing shifts the indices of all later slides by (slides_used - existing_count); a
    caller filling multiple verse sections should fill the later section first, or offset
    subsequent start indices accordingly.

    Raises:
        RuntimeError: if `osascript` is missing (not macOS) or a Keynote script fails.
    """
    ko_box, en_box = read_verse_boxes(key_path, start_index)
    chunks = _chunk_verses(
        verses, ko_box=ko_box, en_box=en_box, ko_min_font=ko_min_font, en_min_font=en_min_font
    )
    target = len(chunks)
    if existing_count > target:
        delete_slides(key_path, start_index + target, existing_count - target)
    elif target > existing_count:
        duplicate_slide(key_path, start_index, target - existing_count)
    for i, vchunk in enumerate(chunks):
        kr_text = "\n".join(f"{v.number}. {v.korean}" for v in vchunk)
        en_text = "\n".join(f"{v.number}. {v.english}" for v in vchunk)
        set_verse_slide(key_path, start_index + i, kr_label, kr_text, en_label, en_text)
    return target


def set_slide_text(key_path: str, slide_index: int, text: str) -> str:
    """Set every on-canvas text item on a slide to `text`, in place (#15).

    Worship-song title and lyric slides each carry a pair of stacked, identical on-canvas text
    items (plus an off-canvas {0,0} leftover); both are set so the visible text stays
    consistent. `text` may contain newlines, which Keynote turns into paragraphs while keeping
    the box's base font. Used for both the title slide and each lyric slide. Returns "ok".

    Raises:
        RuntimeError: if `osascript` is missing (not macOS) or the Keynote script fails.
    """
    key = str(Path(key_path).expanduser())
    return _run_osascript(_SET_SLIDE_TEXT, key, str(slide_index), text).strip()


def set_sermon_title_slide(key_path: str, slide_index: int, title: str, ref: str) -> str:
    """Set the 말씀 title slide's two on-canvas boxes — sermon title + scripture ref — in place (#90).

    The standalone sermon title slide carries a white title box and a gold scripture-reference
    box (plus off-canvas {0,0} leftovers). Unlike a worship title slide, the two boxes hold
    DIFFERENT text, so set_slide_text (which sets every box to one string) would duplicate the
    title across both. Boxes are classified by content — the bracketed one (e.g. "[눅 22:14-24]")
    is the reference — never by index. `ref` includes brackets, e.g. "[히 12:1-2]"; pass "" to
    blank the reference box.

    The title box does not word-wrap or autoshrink, so a long title overflows it (#106 follow-up):
    the box geometry is read and `_fit_title` wraps the title to the fewest readable lines and the
    font shrunk to fit, both applied by the script. Returns "ok".

    Raises:
        RuntimeError: if `osascript` is missing (not macOS) or the Keynote script fails.
    """
    key = str(Path(key_path).expanduser())
    box_w, box_h, base_font = read_title_box(key, slide_index)
    wrapped, font = _fit_title(title, box_w, box_h, base_font)
    return _run_osascript(
        _SET_SERMON_TITLE, key, str(slide_index), wrapped, ref, str(font)
    ).strip()


def set_call_to_worship_ref(key_path: str, slide_index: int, ref: str) -> str:
    """Update the 예배의 부름 reference-display slide's bracketed citation, in place (#107).

    The 예배의 부름 section has a ref-display slide whose single box holds two paragraphs — a static
    "예배의 부름" heading and the bracketed passage citation — separate from the verse-body slide that
    `fill_verse_slides` fills. `build()` never touched it, so its citation kept last week's reference.
    This rewrites paragraph 2 to "[ <ref> ]" (matching the deck's spaced brackets), preserving the
    heading and paragraph styles. `ref` is the bare reference, e.g. "눅 15:19-23". Returns "ok".

    Raises:
        RuntimeError: if `osascript` is missing (not macOS) or the Keynote script fails.
    """
    key = str(Path(key_path).expanduser())
    return _run_osascript(_SET_CTW_REF, key, str(slide_index), f"[ {ref} ]").strip()


def set_sermon_ref_slide(key_path: str, slide_index: int, ref: str) -> str:
    """Update the 말씀 scripture-ref recap slide's two citation boxes, in place (#107).

    A recap slide shown just before the sermon reading carries two on-canvas boxes — a bare Korean
    reference (e.g. "눅 22:14-24") and a bracketed English reference (e.g. "[Luke 22:14-24]") —
    distinct from the verse-body slides that `fill_verse_slides` fills, so `build()` never touched
    it and it kept last week's reference. We classify by the bracket and overwrite each — Korean
    with the raw `ref`, English with the ESV book name in brackets — preserving each box's
    font/color. `ref` is the bare Korean reference, e.g. "삼상 5:1-12". Returns "ok".

    Raises:
        RuntimeError: if `osascript` is missing (not macOS) or the Keynote script fails.
    """
    key = str(Path(key_path).expanduser())
    return _run_osascript(
        _SET_SERMON_REF, key, str(slide_index), ref, f"[{english_ref(ref)}]"
    ).strip()


def set_offering_hymn_title_slide(
    key_path: str, slide_index: int, number: str, title: str
) -> str:
    """Set the 봉헌 title slide's hymn title + number text, in place (#106).

    The 봉헌 title slide is ONE on-canvas box of 3 paragraphs in master.key — a static "봉 헌"
    heading, the bracketed hymn title, then the hymn number — so it keeps paragraph 1 and writes
    `title`/`number` into paragraphs 2/3 (per-paragraph font preserved), mirroring the 성가대
    section-divider in set_choir_title. The two lines are formatted here to match the template's
    existing style: "[ <title> ]" and "(찬 <number>장)". Returns "ok".

    Raises:
        RuntimeError: if `osascript` is missing (not macOS) or the Keynote script fails.
    """
    key = str(Path(key_path).expanduser())
    title_line = f"[ {title} ]"
    number_line = f"(찬 {number}장)"
    return _run_osascript(
        _SET_OFFERING_HYMN_TITLE, key, str(slide_index), title_line, number_line
    ).strip()


def place_image(
    key_path: str, slide_index: int, image_path: str, *, clear_existing: bool = False
) -> str:
    """Place a PNG full-bleed (aspect-fill) on the 1-based slide at slide_index, in place (#22).

    Adds the image and scales it to cover the whole slide, centered: Keynote locks an image's
    aspect ratio, so rather than stretching, the image fills the slide edge-to-edge and any
    overflow past one pair of edges is clipped on export (no margins). When the PNG already
    matches the deck's aspect ratio this is an exact fill. Used for genuinely-image slides:
    downloaded 봉헌 hymn pages, band lead sheets, and media. With clear_existing=True, the slide's
    existing images are deleted first (replace instead of stack) — used to swap last week's hymn
    page for this week's. Returns "ok".

    Raises:
        RuntimeError: if `osascript` is missing (not macOS) or the Keynote script fails.
    """
    key = str(Path(key_path).expanduser())
    # Must be absolute: AppleScript `POSIX file` turns a relative path into a volume-less HFS
    # reference (`file :data:...`), which `make new image` can't load (returns missing value →
    # "Can't get width of missing value"). Hymn-image paths are stored relative (data/runs/...).
    img = str(Path(image_path).expanduser().absolute())
    clear = "1" if clear_existing else "0"
    return _run_osascript(_PLACE_IMAGE, key, str(slide_index), img, clear).strip()


def fill_song_slides(
    key_path: str,
    title_index: int,
    song: Song,
    *,
    existing_lyric_count: int = 1,
) -> int:
    """Fill one worship song's title + lyric slides, resizing the lyric block to fit (#15).

    Sets the title slide at title_index to song.title, chunks song.lines into <=2-line slides
    (lyrics.transcribe.chunk), resizes the lyric block from its template `existing_lyric_count`
    slides to the chunk count (trimming surplus or duplicating the first lyric slide), then
    fills each. A blank/empty `song.lines` yields no chunks: all template lyric slides are
    trimmed and only the title slide remains. Returns the total slides used (1 title + N lyrics).

    Note: resizing shifts the indices of all later slides by (chunks - existing_lyric_count); a
    caller filling several songs should fill the later songs first, or offset later indices.

    Raises:
        RuntimeError: if `osascript` is missing (not macOS) or a Keynote script fails.
    """
    set_slide_text(key_path, title_index, song.title)
    chunks = chunk(song.lines)
    target = len(chunks)
    first_lyric = title_index + 1
    if existing_lyric_count > target:
        delete_slides(key_path, first_lyric + target, existing_lyric_count - target)
    elif target > existing_lyric_count:
        duplicate_slide(key_path, first_lyric, target - existing_lyric_count)
    for i, lines in enumerate(chunks):
        set_slide_text(key_path, first_lyric + i, "\n".join(lines))
    return 1 + target


def set_choir_title(key_path: str, slide_index: int, title: str, composer: str) -> str:
    """Set a 성가대 title slide's song title + composer credit, in place (#88).

    The two choir title slides are laid out differently in master.key. The section-divider slide
    is one box of three paragraphs — a static "성가대 찬양" heading, the title, then the composer —
    so the heading is kept and `title`/`composer` go in paragraphs 2/3 (per-paragraph styling
    preserved). The title-card slide is a single-line lower-third bar, so it takes the combined
    "title composer" line. The script picks the branch per box (heading box vs single-line);
    off-canvas leftovers are skipped. Returns "ok".

    Raises:
        RuntimeError: if `osascript` is missing (not macOS) or the Keynote script fails.
    """
    key = str(Path(key_path).expanduser())
    return _run_osascript(_SET_CHOIR_TITLE, key, str(slide_index), title, composer).strip()


def fill_choir_slides(
    key_path: str,
    title_index: int,
    song: Song,
    *,
    title_count: int = 2,
    existing_lyric_count: int = 17,
) -> int:
    """Fill the 성가대 section: title slides + ≤2-line lyric slides, resizing to fit (#88).

    Sets the song's title + composer on each of the `title_count` title slides starting at
    title_index (`set_choir_title` keeps the static "성가대 찬양" heading), chunks song.lines into
    ≤2-line lyric slides (lyrics.transcribe.chunk), then resizes the lyric block from its template
    `existing_lyric_count` slides to the chunk count (trimming surplus or duplicating the first
    lyric slide) and fills each. The composer credit is shown parenthesized (matching the deck,
    e.g. "(노희석 편곡)") unless the pasted credit already carries its own parentheses. Returns the
    total slides used (title_count + N lyrics).

    Note: resizing shifts the indices of all later slides by (chunks - existing_lyric_count); a
    caller filling later sections must fill them first, or offset later indices.

    Raises:
        RuntimeError: if `osascript` is missing (not macOS) or a Keynote script fails.
    """
    composer = song.composer
    if composer and not composer.startswith("("):
        composer = f"({composer})"
    for i in range(title_count):
        set_choir_title(key_path, title_index + i, song.title, composer)
    chunks = chunk(song.lines)
    target = len(chunks)
    first_lyric = title_index + title_count
    if existing_lyric_count > target:
        delete_slides(key_path, first_lyric + target, existing_lyric_count - target)
    elif target > existing_lyric_count:
        duplicate_slide(key_path, first_lyric, target - existing_lyric_count)
    for i, lines in enumerate(chunks):
        set_slide_text(key_path, first_lyric + i, "\n".join(lines))
    return title_count + target


# A worship-song unit in the template: 3 slides — a blank-green separator, a title slide,
# and one lyric slide — at start_index, +1, +2. fill_song_slides expands the lyric slide.
_WORSHIP_UNIT = 3


def fill_worship_songs(
    key_path: str, start_index: int, section_len: int, songs: list[Song]
) -> int:
    """Fill the 찬양 medley: one [blank separator + title + ≤2-line lyric slides] block per song (#86).

    The template's worship range (`start_index` .. `start_index+section_len-1`) holds last
    week's medley as a sequence of 3-slide unit seeds (blank-green separator, title slide,
    lyric slide). This collapses the range to a single seed unit, fans it out to one unit per
    song, appends a trailing blank separator (matching the deck's blank-before-each-song +
    trailing layout), then fills each unit's title and lyric slides via `fill_song_slides`.

    Fills run back-to-front so each song's lyric expansion (which shifts later indices) leaves
    the still-unfilled earlier units at their predictable positions. Returns the worship
    section's resulting slide count.

    Raises:
        RuntimeError: if `osascript` is missing (not macOS) or a Keynote script fails.
    """
    m = len(songs)
    if m == 0:
        return 0
    s = start_index
    # 1. Collapse the range to one seed unit (blank, title, lyric); drop last week's content.
    delete_slides(key_path, s + _WORSHIP_UNIT, section_len - _WORSHIP_UNIT)
    # 2. Fan the seed unit out to one per song (copies land after the seed's lyric slide).
    if m > 1:
        duplicate_block(key_path, s, _WORSHIP_UNIT, s + _WORSHIP_UNIT - 1, m - 1)
    # 3. Trailing blank separator: copy the seed's blank to after the last unit's lyric slide.
    duplicate_block(key_path, s, 1, s + _WORSHIP_UNIT * m - 1, 1)
    # 4. Fill each unit's title + lyrics, back-to-front (last unit first keeps earlier anchors).
    total = _WORSHIP_UNIT * m + 1  # blank+title+lyric per unit (pre-expansion) + trailing blank
    for i in reversed(range(m)):
        used = fill_song_slides(key_path, s + _WORSHIP_UNIT * i + 1, songs[i])
        total += used - 2  # used = 1 title + L lyrics; the unit already counted 1 title + 1 lyric
    return total


def set_announcement_slide(key_path: str, slide_index: int, text: str) -> str:
    """Set one 교회소식 item slide's native text, styling title gold + detail white (#16).

    `text` is one announcement: paragraph 1 is the title (rendered gold), the remaining
    paragraphs are the detail (rendered white) — matching master.key's item slides, which use a
    single top-anchored box per item with a gold title paragraph over white detail. Both stacked
    on-canvas copies are set; off-canvas {0,0} leftovers are skipped. Returns "ok".

    Raises:
        RuntimeError: if `osascript` is missing (not macOS) or the Keynote script fails.
    """
    key = str(Path(key_path).expanduser())
    return _run_osascript(_SET_ANNOUNCEMENT_SLIDE, key, str(slide_index), text).strip()


def fill_announcement_slides(
    key_path: str,
    start_index: int,
    announcements: list[str],
    *,
    existing_count: int = 1,
) -> int:
    """Fill the 교회소식 block: one native-text slide per announcement, resizing to fit (#16).

    Resizes the announcement block from its template `existing_count` slides to
    len(announcements) (trimming surplus or duplicating the first item slide), then sets each
    slide's native text to one item. Each item string is title (paragraph 1) + detail (the
    remaining paragraphs); set_announcement_slide styles the title gold and the detail white to
    match master.key. Returns the slides used.

    An empty list trims the whole block (target 0); real bulletins always have announcements,
    so this degenerate case is left unguarded (mirrors fill_song_slides' empty-lyrics handling).

    Note: resizing shifts the indices of all later slides by (len - existing_count); a caller
    filling several expanding sections should fill later sections first, or offset later indices.

    Raises:
        RuntimeError: if `osascript` is missing (not macOS) or a Keynote script fails.
    """
    target = len(announcements)
    if existing_count > target:
        delete_slides(key_path, start_index + target, existing_count - target)
    elif target > existing_count:
        duplicate_slide(key_path, start_index, target - existing_count)
    for i, item in enumerate(announcements):
        set_announcement_slide(key_path, start_index + i, item)
    return target


def hymn_image_block(key_path: str, start_index: int, max_scan: int = 20) -> tuple[int, int]:
    """Find last week's 봉헌 hymn-page block: the contiguous image slides at/after start_index.

    The offering-hymn section opens with title/intro slides that carry only native text (no image);
    the hymn pages that follow are flat image slides. So the block to replace is the first run of
    consecutive image-bearing slides scanning forward from start_index (the section anchor),
    bounded by max_scan. Returns (first, last) 1-based indices, or (0, 0) if none are found.

    Raises:
        RuntimeError: if `osascript` is missing (not macOS) or the Keynote script fails.
    """
    key = str(Path(key_path).expanduser())
    out = _run_osascript(_HYMN_IMAGE_BLOCK, key, str(start_index), str(max_scan))
    first, last = (int(x) for x in out.split())
    return first, last


def fill_hymn_slides(key_path: str, section_start: int, image_paths: list[str]) -> int:
    """Fill the 봉헌 block: replace last week's hymn pages with this week's PNGs, aspect-fill (#89).

    The hymn page count varies week to week, so the block can't be a fixed size: hymn_image_block
    detects last week's pages (the contiguous image slides at/after section_start, leaving the
    section's title/intro text slides alone), then resizes that run to len(image_paths) — trimming
    leftover pages or duplicating the first — and place_image(clear_existing=True)s each PNG in
    order, deleting last week's page on each slide first so the new one replaces it rather than
    stacking on top. The list is already trimmed to the verse slides the operator kept in review
    (#84/#25). Returns slides used.

    Note: resizing shifts the indices of all later slides; a caller filling several expanding
    sections should fill later sections first, or offset later indices.

    Raises:
        RuntimeError: if `osascript` is missing (not macOS) or a Keynote script fails, or if no
            existing hymn-image slides are found to replace.
    """
    first, last = hymn_image_block(key_path, section_start)
    if first == 0:
        raise RuntimeError(
            f"No 봉헌 hymn-image slides found at/after slide {section_start} to replace."
        )
    existing_count = last - first + 1
    target = len(image_paths)
    if existing_count > target:
        delete_slides(key_path, first + target, existing_count - target)
    elif target > existing_count:
        duplicate_slide(key_path, first, target - existing_count)
    for i, img in enumerate(image_paths):
        place_image(key_path, first + i, img, clear_existing=True)
    return target


def build(data: ServiceData, template_key: str, out_key: str) -> str:
    """Build the weekly draft deck from the template and the reviewed run store (#29).

    Saves a copy of the template, then fills each section's native text from `data`'s top-level
    section fields (worship_songs / choir_song / *_passage / announcements / sermon_*). Sections
    are filled BACK-TO-FRONT by slide anchor: every expanding fill (verses/announcements/medley)
    shifts the indices of all later slides, so filling the latest section first keeps every
    still-unfilled earlier section at its template anchor. `set_date_slides` is count-neutral
    (in-place text) so it runs first, then the ad-hoc 말씀 special block is dropped (#97) before
    any section fill. Each section is skipped when its content is absent.

    Open-once/save-once (#117): `save_draft` opens the template once and save-as'es it into the
    open draft; every fill mutates that open `front document` in place; `finalize_draft` saves it
    once at the end. `_ensure_keynote_ready` guarantees zero open docs first, so `front document`
    is unambiguously the draft.

    Returns the draft .key path.

    Raises:
        RuntimeError: if `osascript` is missing (not macOS) or a Keynote script fails.
    """
    _ensure_keynote_ready()  # clear stale open docs first, else `open` returns missing value (-1700)
    save_draft(template_key, out_key)

    sermon_bracket = f"[{data.sermon_ref}]" if data.sermon_ref else ""
    set_date_slides(out_key, data.date, data.sermon_title, sermon_bracket)

    # 말씀 ad-hoc special block (135–152, 18 slides): last week's pastor-requested slides
    # (extra songs, message/poem cards) that sit between the sermon-title slide (134) and the
    # recurring 파송의 노래/축도/주기도문 closing. They never recur, so a fresh deck must drop them
    # — the operator adds this week's specials manually in review (#97). Deleted FIRST because it
    # is the highest-index count-changing op in the build: the template anchor 135 is still exact
    # here, every later fill runs at a LOWER index (so this deletion can't shift their anchors,
    # nor they this one). Unconditional — the block is always present in the template, regardless
    # of this week's data. Re-verify the 135/18 anchor whenever master.key is replaced (#98).
    delete_slides(out_key, 135, 18)

    # --- back-to-front: 말씀 title (134) -> 말씀 verses (129) -> 말씀 ref recap (127) -> 교회소식 (117) -> 봉헌 (97) -> 성가대 (77) -> 예배의 부름 (48/47) -> 찬양 medley (6)
    # 말씀 title slide (134): white title box + gold scripture-ref box, before the 129 verse
    # fill resizes/shifts it (#90). Same title/ref the date slides carry.
    if data.sermon_title:
        set_sermon_title_slide(out_key, 134, data.sermon_title, sermon_bracket)

    if data.sermon_passage:
        kr_label, en_label = verse_labels(data.sermon_ref)
        verses = [Verse(**v) for v in data.sermon_passage]
        fill_verse_slides(out_key, 129, kr_label, en_label, verses, existing_count=4)

    # 말씀 scripture-ref recap slide (127): the bare-Korean + bracketed-English ref boxes shown
    # before the sermon reading, distinct from the verse-body slides — must be updated separately
    # or it keeps last week's reference (#107). 127 < 129, so this count-neutral write and the
    # expanding verse fill don't shift each other.
    if data.sermon_ref:
        set_sermon_ref_slide(out_key, 127, data.sermon_ref)

    if data.announcements:
        fill_announcement_slides(out_key, 117, data.announcements, existing_count=5)

    # 봉헌 offering-hymn images: replace last week's pages (detected at/after slide 97, after the
    # section's title/intro slides) with this week's. An empty list (failed/absent download) keeps
    # the template's pages for the operator to fix manually rather than replacing them with none.
    # 봉헌 title slide (97): rewrite the bracketed hymn title + "(찬 N장)" number from this week's
    # parsed values, else it keeps last week's text (#106). Count-neutral (in-place paragraph text),
    # and separate from the image fill so the title updates even when the download returned no pages.
    if data.offering_hymn_number or data.offering_hymn_title:
        set_offering_hymn_title_slide(
            out_key, 97, data.offering_hymn_number, data.offering_hymn_title
        )

    if data.offering_hymn_images:
        fill_hymn_slides(out_key, 97, data.offering_hymn_images)

    if data.choir_song:
        fill_choir_slides(out_key, 77, Song(**data.choir_song))

    # 예배의 부름: the ref-display slide (47) carries the bare Korean + bracketed English citation
    # boxes; the verse-body slide (48) holds the passage text. They are distinct — 47 must be
    # updated separately or it keeps last week's reference (#107). 47 < 48, so the count-neutral
    # ref write and the expanding verse fill don't shift each other.
    if data.call_to_worship_ref:
        set_call_to_worship_ref(out_key, 47, data.call_to_worship_ref)

    if data.call_to_worship_passage:
        kr_label, en_label = verse_labels(data.call_to_worship_ref)
        verses = [Verse(**v) for v in data.call_to_worship_passage]
        fill_verse_slides(out_key, 48, kr_label, en_label, verses, existing_count=1)

    if data.worship_songs:
        songs = [Song(**s) for s in data.worship_songs]
        fill_worship_songs(out_key, 6, 41, songs)

    # Persist every in-place edit with a single save (#117): save_draft opened the deck once and
    # the section fills mutated the open front document; this is the one save that writes them.
    finalize_draft(out_key)
    return out_key


def export_pdf(key_path: str, out_pdf: str) -> str:
    """Export a deck to PDF for phone preview."""
    raise NotImplementedError
