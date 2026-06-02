"""Per-run working-data store: persist a week's ServiceData as JSON.

The run is two-phase (assemble → review → build). This is the shared backbone:
the assemble step writes it, the review app updates it on edit, and the build step
reads the *edited* copy rather than re-parsing. One file per service date under the
git-ignored data/runs/ tree.

Minimal by design — it persists the existing `parse.ServiceData` as-is. When that model
later gains nested fields (lyric `Song`s, verse `Passage`s), `load` will need to
reconstruct those nested types; today every field is JSON-native so `ServiceData(**d)`
round-trips directly.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, fields
from pathlib import Path

from worship_deck.parse import ServiceData

# Where per-run JSON files live (git-ignored). Tests monkeypatch this.
RUNS_DIR = Path("data/runs")

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def path_for(service_date: str) -> Path:
    """Return the run-file path for an ISO (YYYY-MM-DD) service date.

    Validating the format keeps filenames clean and blocks path traversal, since the
    date becomes the filename.
    """
    if not _DATE_RE.fullmatch(service_date):
        raise ValueError(f"service_date must be YYYY-MM-DD, got {service_date!r}")
    return RUNS_DIR / f"{service_date}.json"


def exists(service_date: str) -> bool:
    return path_for(service_date).exists()


def save(service_date: str, data: ServiceData) -> Path:
    """Write `data` to the run file for `service_date`; return the path."""
    dest = path_for(service_date)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(asdict(data), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return dest


def load(service_date: str) -> ServiceData:
    """Read the run file for `service_date` back into ServiceData.

    Unknown keys are ignored so old run files survive the model gaining new fields.
    Raises FileNotFoundError if no run has been saved for that date.
    """
    raw = json.loads(path_for(service_date).read_text(encoding="utf-8"))
    known = {f.name for f in fields(ServiceData)}
    return ServiceData(**{k: v for k, v in raw.items() if k in known})
