"""Build the draft deck by driving Keynote.app via AppleScript/JXA.

Requires a Mac that is powered on and logged in. Starting from the template deck, this
duplicates section slides to fit the week's content, places the rendered PNGs and the
existing hymn image slides in order, and saves data/drafts/draft-YYYY-MM-DD.key plus a
PDF preview for phone review. AppleScript sources live in ./applescript/.
"""

from __future__ import annotations

import math
import subprocess
from pathlib import Path

from worship_deck.bible.verses import Verse
from worship_deck.lyrics.transcribe import Song, chunk

_SAVE_DRAFT = Path(__file__).parent / "applescript" / "save_draft.applescript"
_DUPLICATE_SLIDE = Path(__file__).parent / "applescript" / "duplicate_slide.applescript"
_SET_DATE_SLIDES = Path(__file__).parent / "applescript" / "set_date_slides.applescript"
_SET_VERSE_SLIDE = Path(__file__).parent / "applescript" / "set_verse_slide.applescript"
_READ_VERSE_BOXES = Path(__file__).parent / "applescript" / "read_verse_boxes.applescript"
_DELETE_SLIDES = Path(__file__).parent / "applescript" / "delete_slides.applescript"
_SET_SLIDE_TEXT = Path(__file__).parent / "applescript" / "set_slide_text.applescript"

# --- verse-slide layout model (calibrated against master.key renders) ---------------------
# Keynote exposes no autoshrink/effective-size info via AppleScript, so we estimate how much
# text fits a verse box at a readable font and paginate to keep text from shrinking below it.
_LINE_H = 1.2        # line height as a multiple of font size
_CHAR_W_KO = 1.0     # avg glyph advance / font size — full-width Hangul
_CHAR_W_EN = 0.5     # avg glyph advance / font size — proportional Latin
_MIN_FONT_KO = 60    # readability floor (pt); calibrated so pagination matches master.key's
_MIN_FONT_EN = 44    # slide counts (시 133:1-3 → 1 slide, 눅 22:14-24 → 4) at master's effective sizes


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


def save_draft(template_key: str, out_key: str) -> str:
    """Open the template deck and save a copy to out_key, returning out_key.

    The first Keynote primitive (#20): proves we can drive Keynote over AppleScript.
    Save-As leaves the template untouched. Later issues (#21, #13–16) extend this plumbing
    to duplicate slides and set native text.

    Raises:
        RuntimeError: if `osascript` is missing (not macOS) or the Keynote save fails.
    """
    template = str(Path(template_key).expanduser())
    out = str(Path(out_key).expanduser())
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    _run_osascript(_SAVE_DRAFT, template, out)
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


def build(template_key: str, slides: list[dict], out_key: str) -> str:
    """Generate a fresh deck from the template with the given ordered slides."""
    raise NotImplementedError


def export_pdf(key_path: str, out_pdf: str) -> str:
    """Export a deck to PDF for phone preview."""
    raise NotImplementedError
