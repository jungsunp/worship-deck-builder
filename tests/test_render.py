"""Tests for the render module's background templates.

test_background_templates_exist is CI-safe — it checks the committed PNG assets.
The extraction round-trip test requires macOS + Keynote + TEMPLATE_KEY (local only).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

TEMPLATES_DIR = Path(__file__).parent.parent / "src" / "worship_deck" / "render" / "templates"
BACKGROUNDS = ["date", "verse", "lyrics", "announcement"]
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def test_background_templates_exist() -> None:
    """All 4 backgrounds exist and are valid PNGs (issue #12 done-when)."""
    for name in BACKGROUNDS:
        png = TEMPLATES_DIR / f"{name}.png"
        assert png.exists(), f"missing background: {png}"
        assert png.read_bytes()[: len(PNG_MAGIC)] == PNG_MAGIC, f"not a PNG: {png}"


@pytest.mark.local_only
def test_extraction_produces_four_backgrounds() -> None:
    """Re-running the extractor against the real deck regenerates the 4 PNGs."""
    if not os.getenv("TEMPLATE_KEY"):
        pytest.skip("TEMPLATE_KEY not set")
    script = Path(__file__).parent.parent / "scripts" / "extract_backgrounds.py"
    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    for name in BACKGROUNDS:
        assert (TEMPLATES_DIR / f"{name}.png").exists()
