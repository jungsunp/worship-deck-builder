from __future__ import annotations

import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def real_template_key() -> Path:
    """Real Keynote master template via TEMPLATE_KEY env var — skipped if unset."""
    path = os.getenv("TEMPLATE_KEY")
    if not path or not Path(path).exists():
        pytest.skip("TEMPLATE_KEY not set or file missing")
    return Path(path)


@pytest.fixture(autouse=True)
def _isolated_worship_library(tmp_path_factory, monkeypatch):
    """Point the worship library (#204) at an empty temp dir, so an assemble-time lookup never
    reads the developer's real data/library/worship and greens/reds a test by accident."""
    from worship_deck import library

    monkeypatch.setattr(library, "WORSHIP_DIR", tmp_path_factory.mktemp("worship-library"))
