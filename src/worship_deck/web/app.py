"""Mobile review/trigger web app (FastAPI), reached from the phone over Tailscale.

Flow: see the week's auto-detected songs / announcements / verses, reorder songs and fix
lyric line breaks, then tap Generate. The app calls pipeline.run() on the Mac and returns
a PDF preview of the draft. This is the human-in-the-loop checkpoint.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from dataclasses import asdict, fields
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from worship_deck import hymn, library, obs, parse, pipeline, store
from worship_deck.bible import verses
from worship_deck.keynote import build as keynote_build
from worship_deck.lyrics import linebreak
from worship_deck.lyrics import online as lyrics_online
from worship_deck.lyrics import transcribe as lyrics_transcribe
from worship_deck.lyrics.choir import parse_choir_text
from worship_deck.parse import ServiceData

app = FastAPI(title="Worship Deck")

# Pages are static files (#131): app.py is API-only. review.html reads its date from
# location.pathname, so one file serves every /review/{date}. Shared tokens in app.css.
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}

# Parsed/transcribed fields that are also editable in the review UI. PUT /runs records which of
# these the operator changed (ServiceData.edited_fields) so a re-assemble preserves them (#105).
_EDITABLE_PARSED = (
    "worship_songs",
    "choir_song",
    "confession_song",
    "worship_after_sermon",
    "announcements",
    "offering_hymn_number",
    "offering_hymn_title",
)

# Human-readable labels for the re-assemble confirmation (#105): names exactly which sections a
# re-assemble will keep vs overwrite, so the operator can review before re-assembling.
_EDIT_LABELS = {
    "worship_songs": "찬양 songs (edited lyrics/order)",
    "choir_song": "성가대 choir lyrics (edited)",
    "confession_song": "고백의 찬양 lyrics (edited)",
    "worship_after_sermon": "설교후 찬양 lyrics (edited)",
    "announcements": "교회소식 announcements (edited)",
    "offering_hymn_number": "봉헌 hymn number (edited)",
    "offering_hymn_title": "봉헌 hymn title (edited)",
}
_REFRESH_LABELS = {
    "worship_songs": "찬양 songs (re-transcribed)",
    "choir_song": "성가대 choir lyrics (re-parsed from inbox text)",
    "confession_song": "고백의 찬양 lyrics (re-transcribed)",
    "worship_after_sermon": "설교후 찬양 lyrics (re-transcribed)",
    "announcements": "교회소식 announcements (re-parsed)",
    "offering_hymn_number": "봉헌 hymn number",
    "offering_hymn_title": "봉헌 hymn title",
}


def _kept_on_reassemble(existing: ServiceData) -> list[str]:
    """Labels for the review edits a re-assemble would preserve, for the confirm dialog (#105)."""
    kept: list[str] = []
    # Unedited choir/confession with no inbox input are carried over as-is (edited ones are
    # covered by _EDIT_LABELS below; with inbox input present they refresh instead).
    if (
        existing.choir_song.get("title")
        and "choir_song" not in existing.edited_fields
        and _choir_text() is None
    ):
        kept.append("성가대 choir lyrics")
    if (
        existing.confession_song.get("title")
        and "confession_song" not in existing.edited_fields
        and _confession_path() is None
        and _confession_pick() is None
        and _confession_text() is None
    ):
        kept.append("고백의 찬양 lyrics")
    if (
        existing.worship_after_sermon.get("title")
        and "worship_after_sermon" not in existing.edited_fields
        and _sermon_song_path() is None
        and _sermon_song_text() is None
    ):
        kept.append("설교후 찬양 lyrics")
    if existing.offering_hymn_verses:
        kept.append("봉헌 verse picks (" + ", ".join(str(v) for v in existing.offering_hymn_verses) + ")")
    if existing.sermon_extra_refs:
        kept.append("추가 말씀 구절 (" + ", ".join(existing.sermon_extra_refs) + ")")
    kept += [_EDIT_LABELS[f] for f in existing.edited_fields if f in _EDIT_LABELS]
    return kept


def _refreshed_on_reassemble(existing: ServiceData, hymn_changed: bool) -> list[str]:
    """Labels for the sections a re-assemble would overwrite from the bulletin (#105).

    Bible verses always refresh when their input exists; the editable-parsed fields refresh only
    when the operator has NOT edited them. 봉헌 hymn slides re-download (reselecting every slide)
    only when the hymn number changed — an unchanged hymn keeps the operator's kept subset (#108).
    """
    refreshed: list[str] = []
    if existing.call_to_worship_ref or existing.sermon_ref:
        refreshed.append("Bible verses (예배의 부름 · 말씀)")
    if existing.offering_hymn_number and (hymn_changed or not existing.offering_hymn_images):
        refreshed.append("봉헌 hymn slide images")
    for f in _EDITABLE_PARSED:
        if f in existing.edited_fields:
            continue
        if f.startswith("offering_hymn_") and not existing.offering_hymn_number:
            continue  # no 봉헌 this week — don't list hymn number/title
        if f == "choir_song" and _choir_text() is None:
            continue  # no inbox text — carried over, not refreshed
        if f == "confession_song":
            if _confession_pick() is not None:
                refreshed.append("고백의 찬양 lyrics (라이브러리에서 선택)")
                continue
            if _confession_text() is not None:
                refreshed.append("고백의 찬양 lyrics (직접 입력한 가사에서 다시 파싱)")
                continue
            if _confession_path() is None:
                continue  # no inbox image/text — carried over, not refreshed
        refreshed.append(_REFRESH_LABELS[f])
    return refreshed

# Per-run assemble status, keyed by ISO service date. In-memory is enough: a single-process
# uvicorn on the Mac drives the whole run (status is lost on restart, which is acceptable).
_STATUS: dict[str, dict] = {}

# Per-run build status, keyed by ISO service date. Separate from _STATUS so a build doesn't
# clobber the assemble status the same date already carries.
_BUILD_STATUS: dict[str, dict] = {}

# Uploaded bulletin/sheet files land here — a fixed local dir under the git-ignored
# data/ tree (no env var: files arrive via the upload form, not an iCloud drop-folder).
# Tests monkeypatch this to a tmp dir.
INBOX_DIR = Path("data/inbox")

# Downloaded offering-hymn slide PNGs land under HYMN_DIR/<service_date>/hymn/ (git-ignored,
# alongside the run-store JSON). Tests monkeypatch this to a tmp dir.
HYMN_DIR = Path("data/runs")

# Custom 찬양 section labels the operator typed via 직접입력 (e.g. C1, C2), reused across weeks
# in the medley label dropdown. Flat JSON list, git-ignored. Tests monkeypatch this.
LABELS_FILE = Path("data/custom_labels.json")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# Each required source has a dedicated upload slot (#109); slot identity is the reserved
# inbox filename: bulletin.pdf, confession.<ext>, sermonsong.<ext>, sheet-<origname>, choir.txt.
def _kind(name: str) -> str:
    if name == "bulletin.pdf":
        return "bulletin"
    if name.startswith("confession."):
        return "confession"
    if name.startswith("sermonsong."):
        return "sermonsong"
    if name.startswith("sheet-"):
        return "sheet"
    return "other"


@app.post("/upload/{kind}")
def upload(kind: str, files: list[UploadFile] = File(...)) -> dict:
    """Save uploads into the slot's reserved inbox name (#109).

    Single-file slots (bulletin, confession) replace the existing file; medley sheets keep
    their original (sanitized) names behind a constant prefix so filename order is preserved.
    Called by the home page's fetch-on-select JS, so it returns JSON, not a page.
    """
    if kind not in ("bulletin", "sheets", "confession", "sermonsong"):
        raise HTTPException(status_code=400, detail="unknown upload slot")
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for f in files[: None if kind == "sheets" else 1]:
        name = Path(f.filename or "").name  # strip any path components (e.g. ../)
        if not name:
            continue
        suffix = Path(name).suffix.lower()
        if kind == "bulletin":
            if suffix != ".pdf":
                raise HTTPException(status_code=400, detail="bulletin must be a PDF")
            name = "bulletin.pdf"
        elif kind == "confession":
            if suffix not in _IMAGE_SUFFIXES:
                raise HTTPException(status_code=400, detail="confession sheet must be an image")
            for old in INBOX_DIR.glob("confession.*"):  # replace — extension may change
                old.unlink()
            _confession_pick_file().unlink(missing_ok=True)  # image and library pick are exclusive
            name = f"confession{suffix}"
        elif kind == "sermonsong":
            if suffix not in _IMAGE_SUFFIXES:
                raise HTTPException(status_code=400, detail="설교후 찬양 sheet must be an image")
            for old in INBOX_DIR.glob("sermonsong.*"):  # replace image + text (exclusive inputs)
                old.unlink()
            name = f"sermonsong{suffix}"
        else:
            if suffix not in _IMAGE_SUFFIXES:
                raise HTTPException(status_code=400, detail="sheets must be images")
            name = f"sheet-{name}"
        with (INBOX_DIR / name).open("wb") as out:
            shutil.copyfileobj(f.file, out)
        saved.append(name)
    return {"saved": saved}


@app.post("/inbox/choir")
def save_choir_text(body: dict = Body(...)) -> dict:
    """Write the 성가대 lyrics textarea into the inbox choir.txt (blank text clears it)."""
    text = body.get("text", "")
    target = INBOX_DIR / "choir.txt"
    if text.strip():
        INBOX_DIR.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return {"saved": True}
    if target.is_file():
        target.unlink()
    return {"saved": False}


@app.get("/inbox")
def inbox() -> dict:
    """Current inbox contents (filename + size + slot kind), plus the saved choir text.

    choir.txt is excluded from `files` — the home-page textarea is its UI.
    """
    if not INBOX_DIR.exists():
        return {
            "files": [], "choir_text": "", "confession_pick": "",
            "confession_text": "", "sermonsong_text": "",
        }
    # Sidecars have their own textarea/picker UI, not a file slot.
    _sidecars = {"choir.txt", "confession-pick.json", "confession.txt", "sermonsong.txt"}
    files = sorted(p for p in INBOX_DIR.iterdir() if p.is_file() and p.name not in _sidecars)
    pick = _confession_pick()
    return {
        "files": [{"name": p.name, "size": p.stat().st_size, "kind": _kind(p.name)} for p in files],
        "choir_text": _choir_text() or "",
        "confession_pick": pick.get("title", "") if pick else "",
        "confession_text": _confession_text() or "",
        "sermonsong_text": _sermon_song_text() or "",
    }


@app.delete("/inbox")
def clear_inbox() -> dict:
    """Empty the inbox (uploads + choir text) — the home page's new-week reset button.

    Past runs under data/runs/ are untouched; this only clears next week's input slots.
    """
    files = [p for p in INBOX_DIR.iterdir() if p.is_file()] if INBOX_DIR.exists() else []
    for p in files:
        p.unlink()
    return {"deleted": len(files)}


@app.delete("/inbox/{name}")
def delete_inbox_file(name: str) -> dict:
    """Remove one uploaded file, path-safe (same guard as /upload: name must have no path parts)."""
    if Path(name).name != name:
        raise HTTPException(status_code=400, detail="invalid filename")
    target = INBOX_DIR / name
    if not target.is_file():
        raise HTTPException(status_code=404, detail="not found")
    target.unlink()
    return {"deleted": name}


@app.get("/library/confession")
def list_confession_library() -> dict:
    """Saved 고백의 찬양 songs for the home picker (#issue): {slug, title, composer}."""
    return {"songs": library.list_songs()}


@app.post("/library/confession")
def save_confession_library(body: dict = Body(...)) -> dict:
    """Save a polished confession song to the cross-week library; return its slug + title."""
    try:
        slug = library.save_song(body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"slug": slug, "title": body.get("title", "")}


@app.post("/inbox/confession-pick")
def pick_confession(body: dict = Body(...)) -> dict:
    """Pick a saved library song as this week's 고백의 찬양 input (alternative to an image).

    Snapshots the full song into the inbox so assemble stays decoupled from the library, and
    removes any uploaded confession image — the two inputs are mutually exclusive.
    """
    song = library.load_song(body.get("slug", ""))
    if song is None:
        raise HTTPException(status_code=404, detail="song not in library")
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    for old in INBOX_DIR.glob("confession.*"):
        old.unlink()
    _confession_pick_file().write_text(json.dumps(song, ensure_ascii=False), encoding="utf-8")
    return {"title": song.get("title", "")}


@app.post("/inbox/confession-text")
def save_confession_text(body: dict = Body(...)) -> dict:
    """Write typed 고백의 찬양 lyrics into the inbox confession.txt — the text-input alternative
    to an image or a library pick (same title/composer/lyrics format as 성가대, #109).

    Non-empty text clears the uploaded image and library pick so the three confession inputs
    stay mutually exclusive (mirrors the image↔pick exclusivity); blank text clears the slot.
    """
    text = body.get("text", "")
    target = INBOX_DIR / "confession.txt"
    if text.strip():
        INBOX_DIR.mkdir(parents=True, exist_ok=True)
        for old in INBOX_DIR.glob("confession.*"):  # drop a competing uploaded image
            if old.suffix.lower() in _IMAGE_SUFFIXES:
                old.unlink()
        _confession_pick_file().unlink(missing_ok=True)
        target.write_text(text, encoding="utf-8")
        return {"saved": True}
    if target.is_file():
        target.unlink()
    return {"saved": False}


@app.post("/inbox/sermonsong-text")
def save_sermonsong_text(body: dict = Body(...)) -> dict:
    """Write typed 설교후 찬양 lyrics into the inbox sermonsong.txt — the text-input alternative
    to an uploaded sheet image (same title/composer/lyrics format as 성가대).

    Non-empty text clears a competing uploaded image so the two inputs stay mutually exclusive;
    blank text clears the slot.
    """
    text = body.get("text", "")
    target = INBOX_DIR / "sermonsong.txt"
    if text.strip():
        INBOX_DIR.mkdir(parents=True, exist_ok=True)
        for old in INBOX_DIR.glob("sermonsong.*"):  # drop a competing uploaded image
            if old.suffix.lower() in _IMAGE_SUFFIXES:
                old.unlink()
        target.write_text(text, encoding="utf-8")
        return {"saved": True}
    if target.is_file():
        target.unlink()
    return {"saved": False}


@app.get("/api/labels")
def list_labels() -> dict:
    """Custom medley section labels the operator has saved (직접입력), for the label dropdown."""
    if not LABELS_FILE.exists():
        return {"labels": []}
    return {"labels": json.loads(LABELS_FILE.read_text(encoding="utf-8"))}


@app.post("/api/labels")
def add_label(body: dict = Body(...)) -> dict:
    """Remember a newly typed custom label so future runs can pick it from the dropdown."""
    label = (body.get("label") or "").strip()
    if not label:
        raise HTTPException(status_code=400, detail="empty label")
    labels = json.loads(LABELS_FILE.read_text(encoding="utf-8")) if LABELS_FILE.exists() else []
    if label not in labels:
        labels.append(label)
        LABELS_FILE.parent.mkdir(parents=True, exist_ok=True)
        LABELS_FILE.write_text(json.dumps(labels, ensure_ascii=False), encoding="utf-8")
    return {"labels": labels}


def _bulletin_path() -> Path | None:
    """The inbox bulletin PDF (fixed slot name), or None if none uploaded."""
    pdf = INBOX_DIR / "bulletin.pdf"
    return pdf if pdf.is_file() else None


def _sheet_paths() -> list[Path]:
    """Band lead-sheet images in the inbox, in filename order (medley page order)."""
    return sorted(p for p in INBOX_DIR.glob("sheet-*") if p.suffix.lower() in _IMAGE_SUFFIXES)


def _confession_path() -> Path | None:
    """The 고백의 찬양 sheet image in the inbox, or None if none uploaded."""
    imgs = sorted(p for p in INBOX_DIR.glob("confession.*") if p.suffix.lower() in _IMAGE_SUFFIXES)
    return imgs[0] if imgs else None


def _confession_pick_file() -> Path:
    """Path of the inbox sidecar holding a library-picked confession song (may not exist)."""
    return INBOX_DIR / "confession-pick.json"


def _confession_pick() -> dict | None:
    """The library song picked for this week (snapshotted into the inbox), or None."""
    f = _confession_pick_file()
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None


def _confession_text() -> str | None:
    """Typed 고백의 찬양 lyrics from the inbox (the text-input alternative to an image), or None."""
    target = INBOX_DIR / "confession.txt"
    if not target.is_file():
        return None
    text = target.read_text(encoding="utf-8")
    return text if text.strip() else None


def _sermon_song_path() -> Path | None:
    """The 설교후 찬양 sheet image in the inbox, or None if none uploaded."""
    imgs = sorted(p for p in INBOX_DIR.glob("sermonsong.*") if p.suffix.lower() in _IMAGE_SUFFIXES)
    return imgs[0] if imgs else None


def _sermon_song_text() -> str | None:
    """Typed 설교후 찬양 lyrics from the inbox (the text-input alternative to an image), or None."""
    target = INBOX_DIR / "sermonsong.txt"
    if not target.is_file():
        return None
    text = target.read_text(encoding="utf-8")
    return text if text.strip() else None


def _choir_text() -> str | None:
    """The saved 성가대 lyrics text from the inbox, or None if absent/blank."""
    target = INBOX_DIR / "choir.txt"
    if not target.is_file():
        return None
    text = target.read_text(encoding="utf-8")
    return text if text.strip() else None


def _assemble_async(service_date: str) -> None:
    """Run the long read-only steps (transcribe + verses) and update the run + status.

    FastAPI runs this in a threadpool after the response is sent. Failures are caught
    and recorded in `_STATUS` so the page reports them instead of the worker crashing.
    """
    logger = obs.configure_logging()
    t0 = time.monotonic()
    steps: dict[str, float] = {}
    try:
        data = store.load(service_date)
        warnings: list[str] = []  # missing-slot / best-effort failures; joined into the status

        _STATUS[service_date] = {"status": "running", "step": "transcribe", "error": None}
        # Skip re-transcription if the operator already hand-edited the medley (#105) — a
        # re-assemble must not clobber their line-break/order fixes.
        if "worship_songs" not in data.edited_fields:
            if not _sheet_paths():
                warnings.append("no 찬양 sheet images in inbox — medley not transcribed")
            songs = []
            for i, img in enumerate(_sheet_paths()):
                sheet_steps: dict[str, float] = {}
                result = lyrics_transcribe.transcribe(str(img), steps=sheet_steps)
                songs.extend(result)
                for k, v in sheet_steps.items():
                    steps[f"{k}_sheet_{i}"] = v
            data.worship_songs = [asdict(s) for s in songs]

        # 고백의 찬양 (#109): one of three inputs — a library-picked song (snapshotted in the
        # inbox) or typed lyrics are used as-is (no OCR, parsed like 성가대); otherwise transcribe
        # its dedicated sheet image. Best-effort like the hymn below — a transcription hiccup must
        # not discard the rest of the assemble.
        if "confession_song" not in data.edited_fields:
            pick = _confession_pick()
            text = _confession_text()
            img = _confession_path()
            if pick is not None:
                pick.pop("provenance", None)  # library song is trustworthy; show no badge (#200)
                data.confession_song = pick
            elif text is not None:
                data.confession_song = asdict(parse_choir_text(text))
            elif img is None:
                warnings.append("no 고백의 찬양 input (image, text, or library pick) in inbox")
            else:
                try:
                    confession_steps: dict[str, float] = {}
                    confession = lyrics_transcribe.transcribe(str(img), steps=confession_steps)
                    for k, v in confession_steps.items():
                        steps[f"{k}_confession"] = v
                    if confession:
                        data.confession_song = asdict(confession[0])
                    else:
                        warnings.append("고백의 찬양 transcription found no lyrics")
                except Exception:  # noqa: BLE001 - best-effort, surface as a warning
                    logger.exception("고백의 찬양 transcription failed for %s", service_date)
                    warnings.append("고백의 찬양 transcription failed — edit it in review")

        # 설교후 찬양: optional worship song after the sermon — typed lyrics (parsed like 성가대,
        # no OCR) or a dedicated sheet image. Absent input just leaves the section empty (the whole
        # section is optional), so no warning. Best-effort like the confession above.
        if "worship_after_sermon" not in data.edited_fields:
            text = _sermon_song_text()
            img = _sermon_song_path()
            if text is not None:
                data.worship_after_sermon = asdict(parse_choir_text(text))
            elif img is not None:
                try:
                    sermonsong_steps: dict[str, float] = {}
                    result = lyrics_transcribe.transcribe(str(img), steps=sermonsong_steps)
                    for k, v in sermonsong_steps.items():
                        steps[f"{k}_sermonsong"] = v
                    if result:
                        data.worship_after_sermon = asdict(result[0])
                    else:
                        warnings.append("설교후 찬양 transcription found no lyrics")
                except Exception:  # noqa: BLE001 - best-effort, surface as a warning
                    logger.exception("설교후 찬양 transcription failed for %s", service_date)
                    warnings.append("설교후 찬양 transcription failed — edit it in review")

        # 성가대 (#109): parsed from the home-page choir text saved into the inbox.
        if "choir_song" not in data.edited_fields:
            text = _choir_text()
            if text is None:
                warnings.append("no 성가대 choir lyrics text in inbox")
            else:
                data.choir_song = asdict(parse_choir_text(text))

        _STATUS[service_date] = {"status": "running", "step": "verses", "error": None}
        tb = time.monotonic()
        if data.call_to_worship_ref:
            data.call_to_worship_passage = [asdict(v) for v in verses.lookup_verses(data.call_to_worship_ref)]
        if data.sermon_ref:
            data.sermon_passage = [asdict(v) for v in verses.lookup_verses(data.sermon_ref)]
        steps["bible"] = round(time.monotonic() - tb, 1)

        # Best-effort: a failed/forbidden hymn download must not discard the transcribe/verses
        # work above. On failure we record a warning and leave offering_hymn_images empty so
        # the operator can add the hymn manually.
        _STATUS[service_date] = {"status": "running", "step": "hymn", "error": None}
        th = time.monotonic()
        # Skip the fetch when a kept slide subset is already present (re-assemble carried the
        # operator's #108 selection over) — re-fetching would reselect every slide.
        if data.offering_hymn_number and not data.offering_hymn_images:
            try:
                pngs = hymn.fetch_hymn_slides(
                    data.offering_hymn_number, HYMN_DIR / service_date / "hymn"
                )
                data.offering_hymn_images = [str(p) for p in pngs]
            except Exception:  # noqa: BLE001 - download is best-effort, surface as a warning
                logger.exception(
                    "Hymn fetch failed for %s (hymn %s)", service_date, data.offering_hymn_number
                )
                warnings.append(f"hymn {data.offering_hymn_number} download failed — add it manually")
        steps["hymn"] = round(time.monotonic() - th, 1)

        store.save(service_date, data)
        total = round(time.monotonic() - t0, 1)
        _STATUS[service_date] = {
            "status": "done",
            "step": None,
            "error": None,
            "warning": "\n".join(warnings) or None,
            "seconds": total,
            "steps": steps,
        }
        obs.write_run_record(service_date, "assemble", True, total, steps)
        logger.info("Assembled run for %s (%d song(s)) in %.1fs", service_date, len(data.worship_songs), total)
    except Exception as e:  # noqa: BLE001 - surface to the page, don't crash the worker
        logger.exception("Assemble failed for %s", service_date)
        total = round(time.monotonic() - t0, 1)
        _STATUS[service_date] = {"status": "error", "step": None, "error": repr(e), "seconds": total, "steps": steps}
        obs.write_run_record(service_date, "assemble", False, total, steps, repr(e))


@app.post("/assemble")
def assemble(background_tasks: BackgroundTasks, confirm: bool = False) -> dict:
    """Parse the inbox bulletin (fast, sync) then kick off transcribe + verses async.

    Parsing runs in-request so a missing bulletin / undetectable date fails immediately
    and we can return the detected service date as the poll key.

    Re-assembling a date that already has a run is destructive (#105): the fresh parse would
    wipe review edits. We warn first (return needs_confirm) unless `confirm`, then merge —
    preserving hymn verse picks, any operator-edited parsed fields, and carrying over
    choir/confession (refreshed from the inbox only when unedited and the input exists).
    """
    pdf = _bulletin_path()
    if pdf is None:
        raise HTTPException(status_code=400, detail="no bulletin (PDF) in inbox")

    data = parse.parse(str(pdf))
    try:
        service_date = parse.to_iso_date(data.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="could not detect service date in bulletin")

    existing = store.load(service_date) if store.exists(service_date) else None
    # Whether the 봉헌 hymn changed vs the stored run — the freshly parsed number differs from
    # what the stored slides were fetched for (including an operator-edited number, which the
    # merge below restores). Drives whether the operator's kept slide subset survives or gets
    # re-fetched fresh (below and in _refreshed). (data.offering_hymn_number is the fresh parse
    # here, pre-merge.)
    hymn_changed = existing is not None and data.offering_hymn_number != existing.offering_hymn_number
    if existing is not None and not confirm:
        return {
            "service_date": service_date,
            "needs_confirm": True,
            "kept": _kept_on_reassemble(existing),
            "refresh": _refreshed_on_reassemble(existing, hymn_changed),
        }
    if existing is not None:
        data.edited_fields = list(existing.edited_fields)
        # Carry over choir/confession as the baseline; _assemble_async refreshes them from the
        # inbox only when unedited and the inbox input exists.
        data.choir_song = existing.choir_song
        data.confession_song = existing.confession_song
        data.offering_hymn_verses = existing.offering_hymn_verses
        data.sermon_extra_refs = existing.sermon_extra_refs
        data.sermon_extra_passages = existing.sermon_extra_passages
        # Preserve the operator's kept 봉헌 slide subset (#108) unless the hymn changed; leaving
        # it non-empty makes _assemble_async skip the re-fetch that would reselect all slides.
        if not hymn_changed:
            data.offering_hymn_images = existing.offering_hymn_images
        for f in existing.edited_fields:  # preserve operator-edited parsed fields
            setattr(data, f, getattr(existing, f))

    store.save(service_date, data)
    _STATUS[service_date] = {"status": "running", "step": "transcribe", "error": None}
    background_tasks.add_task(_assemble_async, service_date)
    return {"service_date": service_date, "status_url": f"/assemble/{service_date}/status"}


@app.get("/assemble/{service_date}/status")
def assemble_status(service_date: str) -> dict:
    try:
        store.path_for(service_date)  # validate the date shape
    except ValueError:
        raise HTTPException(status_code=400, detail="service_date must be YYYY-MM-DD")
    return _STATUS.get(service_date, {"status": "unknown"})


# ── Review / edit the assembled run ───────────────────────────────────────────


@app.get("/review/{service_date}")
def review(service_date: str) -> FileResponse:
    return FileResponse(STATIC_DIR / "review.html")


@app.get("/history")
def history() -> FileResponse:
    return FileResponse(STATIC_DIR / "runs.html")


@app.get("/perf")
def perf_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "perf.html")


@app.get("/api/perf")
def perf_data() -> dict:
    """All run records from logs/runs.jsonl, newest first, for the performance dashboard."""
    runs_file = obs.LOG_DIR / "runs.jsonl"
    if not runs_file.is_file():
        return {"runs": []}
    records = []
    with runs_file.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    records.reverse()
    return {"runs": records}


@app.get("/runs")
def list_runs() -> dict:
    """Assembled runs by service date, newest first, for the home page to link to review.

    `pdfs` lists the dates whose built draft PDF still exists on disk (#102), so /history can
    show a persistent download link — the post-build link in review is in-memory only and is
    lost on reload.
    """
    if not store.RUNS_DIR.exists():
        return {"runs": [], "pdfs": []}
    runs = sorted((p.stem for p in store.RUNS_DIR.glob("*.json")), reverse=True)
    pdfs = [d for d in runs if Path(f"data/drafts/draft-{d}.pdf").is_file()]
    return {"runs": runs, "pdfs": pdfs}


@app.get("/runs/{service_date}")
def get_run(service_date: str) -> dict:
    """Return the assembled run JSON for the review page to render."""
    try:
        store.path_for(service_date)  # validate the date shape
    except ValueError:
        raise HTTPException(status_code=400, detail="service_date must be YYYY-MM-DD")
    try:
        return asdict(store.load(service_date))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="no run for that date")


@app.put("/runs/{service_date}")
def put_run(service_date: str, body: dict = Body(...)) -> dict:
    """Persist the operator's edits (full-object replace; the page round-trips the whole run)."""
    try:
        store.path_for(service_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="service_date must be YYYY-MM-DD")
    known = {f.name for f in fields(ServiceData)}
    existing = store.load(service_date) if store.exists(service_date) else None
    data = ServiceData(**{k: v for k, v in body.items() if k in known})
    data.offering_hymn_verses = [int(v) for v in data.offering_hymn_verses]
    # The single-song sections seed an empty V1 card in review; an untouched section must read as
    # "no content" (title-less, no lyrics) so it isn't built and isn't flagged as an edit (#105).
    for f in ("worship_after_sermon", "confession_song"):
        song = getattr(data, f)
        if not song.get("title") and not any((ln or "").strip() for ln in song.get("lines", [])):
            setattr(data, f, {})
    # Extra sermon refs (#114) are looked up on save, not at build: a typo'd ref fails here
    # with a visible warning instead of a minute into the Keynote build, and the review page
    # can preview the verses. Only changed refs hit the network; a failed lookup stores an
    # empty passage (build skips it) and the save still succeeds.
    warnings: list[str] = []
    # Operator-typed refs: trim, and collapse stray spaces around ':' and '-' ("시 4: 15-20" →
    # "시 4:15-20") so parse_ref accepts them and the slide label shows the clean form.
    data.sermon_extra_refs = [
        re.sub(r"\s*([:-])\s*", r"\1", r.strip()) for r in data.sermon_extra_refs if r.strip()
    ]
    if data.sermon_extra_refs != (existing.sermon_extra_refs if existing else []):
        data.sermon_extra_passages = []
        for ref in data.sermon_extra_refs:
            try:
                data.sermon_extra_passages.append([asdict(v) for v in verses.lookup_verses(ref)])
            except Exception:  # noqa: BLE001 - bad ref or lookup hiccup; keep the other edits
                data.sermon_extra_passages.append([])
                warnings.append(f"추가 말씀 구절 '{ref}' 조회 실패 — 확인 후 다시 저장")
    # Record which parsed/transcribed fields the operator actually changed, so a later
    # re-assemble preserves them instead of re-deriving them (#105). The pure-human fields
    # (offering_hymn_verses, sermon_extra_*) are always preserved, so they aren't tracked.
    edited = set(existing.edited_fields) if existing else set()
    if existing:
        edited |= {f for f in _EDITABLE_PARSED if getattr(data, f) != getattr(existing, f)}
    data.edited_fields = sorted(edited)
    store.save(service_date, data)
    return {"saved": service_date, "warnings": warnings} if warnings else {"saved": service_date}


def _song_by_ref(data: ServiceData, ref: str) -> dict | None:
    """Resolve a review song reference to its stored dict — mirrors review.html's songByRef.

    ``ref`` is a numeric string index into the 찬양 medley, or "confession"/"sermonsong" for the
    single-song sections. Returns None when the ref doesn't resolve to a present song.
    """
    if ref == "confession":
        return data.confession_song or None
    if ref == "sermonsong":
        return data.worship_after_sermon or None
    try:
        return data.worship_songs[int(ref)]
    except (ValueError, IndexError):
        return None


@app.post("/runs/{service_date}/research")
def research_song(service_date: str, body: dict = Body(...)) -> dict:
    """Re-run the gasazip lookup for one song from an operator-corrected title (#203).

    Scores candidates against the song's stored OCR fragments (persisted at assemble) and
    returns the top matches for the operator to pick from — the HITL fix when the automatic
    lookup landed on the wrong song. Read-only: the pick is applied via /research/apply + PUT.
    """
    ref, title = str(body.get("ref", "")), (body.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    try:
        data = store.load(service_date)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="no run for that date")
    song = _song_by_ref(data, ref)
    if song is None:
        raise HTTPException(status_code=404, detail="unknown song ref")
    fragments = song.get("fragments", [])
    try:
        cands = lyrics_online.search_scored(title, fragments)
    except httpx.HTTPError:
        return {"candidates": [], "error": "가사집 검색 실패 — 잠시 후 다시 시도하세요"}
    return {
        # scored=False means this song predates fragment persistence (or was typed) — the match %s
        # are meaningless, so the UI hides them and the operator picks by lyric preview. A re-assemble
        # re-transcribes the song and stores its fragments, restoring the match scores.
        "scored": bool(fragments),
        "candidates": [
            {
                "song_id": c.song_id, "title": c.title, "artist": c.artist,
                "cand_cov": c.cand_cov, "ocr_cov": c.ocr_cov,
                "preview": [ln for ln in c.lines if ln.strip()][:4],
            }
            for c in cands
        ]
    }


@app.post("/runs/{service_date}/research/apply")
def apply_research(service_date: str, body: dict = Body(...)) -> dict:
    """Fetch a chosen gasazip candidate's lyrics and rebreak them like assemble does (#203).

    Pure transform — the client sets the song's lines/provenance in the run object and persists
    via PUT /runs (matching the existing edit flow). Rebreaking only the picked candidate avoids
    the wasted work of rebreaking every candidate in /research.
    """
    song_id = str(body.get("song_id", "")).strip()
    if not song_id:
        raise HTTPException(status_code=400, detail="song_id is required")
    cand = lyrics_online.Candidate(
        song_id=song_id, title=(body.get("title") or ""), artist=(body.get("artist") or "")
    )
    try:
        cand.lines = lyrics_online.fetch_lyrics(song_id)
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="가사집 가사 조회 실패")
    lyrics_online._strip_header(cand)
    return {"lines": linebreak.rebreak(cand.lines)}


@app.get("/runs/{service_date}/hymn")
def list_hymn_slides(service_date: str) -> dict:
    """List every downloaded 봉헌 hymn PNG (slide order) for the review grid (#84/#108).

    Paths match how _assemble_async stores them (str(HYMN_DIR/<date>/hymn/<name>)) so the
    client can membership-check them against the kept offering_hymn_images list.
    """
    try:
        store.path_for(service_date)  # validate the date shape
    except ValueError:
        raise HTTPException(status_code=400, detail="service_date must be YYYY-MM-DD")
    hymn_dir = HYMN_DIR / service_date / "hymn"
    if not hymn_dir.is_dir():
        return {"images": []}
    pngs = sorted(p for p in hymn_dir.iterdir() if p.suffix.lower() == ".png")
    return {"images": [str(p) for p in pngs]}


@app.get("/runs/{service_date}/hymn/{name}")
def get_hymn_slide(service_date: str, name: str) -> FileResponse:
    """Serve one hymn PNG for the review thumbnail grid, path-safe (mirrors /inbox guards)."""
    try:
        store.path_for(service_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="service_date must be YYYY-MM-DD")
    if Path(name).name != name:
        raise HTTPException(status_code=400, detail="invalid filename")
    target = HYMN_DIR / service_date / "hymn" / name
    if not target.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(target)


@app.get("/runs/{service_date}/draft.pdf")
def draft_pdf(service_date: str) -> FileResponse:
    """Serve the built draft's PDF preview for inline review on the phone (#23)."""
    try:
        store.path_for(service_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="service_date must be YYYY-MM-DD")
    pdf = Path(f"data/drafts/draft-{service_date}.pdf").resolve()
    if not pdf.is_file():
        raise HTTPException(status_code=404, detail="not built yet")
    return FileResponse(pdf, media_type="application/pdf")


# ── Build (Generate) ─────────────────────────────────────────────────────────


def _build_async(service_date: str) -> None:
    """Drive Keynote to build the draft .key from the reviewed run, then open it on the Mac.

    FastAPI runs this in a threadpool after the response is sent. The build is slow
    (~60–90s, real Keynote) and local_only, so it must not block the phone's request.
    Failures are caught and recorded in `_BUILD_STATUS` so the page reports them.
    After the build, export a PDF of the still-open draft (#23) so the phone can preview
    the rendered slides inline — the browser can't render a .key and the file is Mac-local.
    """
    logger = obs.configure_logging()
    t0 = time.monotonic()
    try:
        path = pipeline.run(service_date)
        # Export the PDF preview from the still-open draft (#23). Best-effort: the build already
        # succeeded, so a failed export shouldn't flip the status to error — just no preview link.
        pdf_url = None
        try:
            keynote_build.export_pdf(str(Path(path).with_suffix(".pdf")))
            pdf_url = f"/runs/{service_date}/draft.pdf"
        except Exception:  # noqa: BLE001 - preview is optional; the deck itself is the deliverable
            logger.exception("PDF preview export failed for %s", service_date)
        # Open the draft in Keynote on the Mac (operator is at the machine). Best-effort:
        # the build already succeeded, so a failed `open` shouldn't flip the status to error.
        subprocess.run(["open", path], check=False)
        total = round(time.monotonic() - t0, 1)
        _BUILD_STATUS[service_date] = {"status": "done", "path": path, "pdf": pdf_url, "error": None, "seconds": total}
        logger.info("Built draft for %s at %s in %.1fs", service_date, path, total)
    except Exception as e:  # noqa: BLE001 - surface to the page, don't crash the worker
        logger.exception("Build failed for %s", service_date)
        _BUILD_STATUS[service_date] = {"status": "error", "path": None, "error": repr(e), "seconds": round(time.monotonic() - t0, 1)}


@app.post("/runs/{service_date}/build")
def build_run(service_date: str, background_tasks: BackgroundTasks) -> dict:
    """Kick off the Keynote build for an assembled+reviewed run; poll the status_url for the path."""
    try:
        store.path_for(service_date)  # validate the date shape
    except ValueError:
        raise HTTPException(status_code=400, detail="service_date must be YYYY-MM-DD")
    if not store.exists(service_date):
        raise HTTPException(status_code=404, detail="no run for that date")
    _BUILD_STATUS[service_date] = {"status": "running", "path": None, "error": None}
    background_tasks.add_task(_build_async, service_date)
    return {"service_date": service_date, "status_url": f"/runs/{service_date}/build/status"}


@app.get("/runs/{service_date}/build/status")
def build_status(service_date: str) -> dict:
    try:
        store.path_for(service_date)  # validate the date shape
    except ValueError:
        raise HTTPException(status_code=400, detail="service_date must be YYYY-MM-DD")
    return _BUILD_STATUS.get(service_date, {"status": "unknown"})
