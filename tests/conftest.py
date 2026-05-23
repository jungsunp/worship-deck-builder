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
