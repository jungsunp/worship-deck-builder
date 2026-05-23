"""Tests for committed test fixtures.

All three tests are CI-safe — no macOS/Keynote required.
The real_template_key test requires TEMPLATE_KEY to be set (local only).
"""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

import pdfplumber
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def test_bulletin_fixture_is_valid_pdf() -> None:
    """Sanitized bulletin has extractable text with key fields present."""
    logging.disable(logging.WARNING)  # silence pdfminer FontBBox noise
    try:
        with pdfplumber.open(FIXTURES / "sample_bulletin.pdf") as pdf:
            assert len(pdf.pages) >= 1
            text = "".join(p.extract_text() or "" for p in pdf.pages)
    finally:
        logging.disable(logging.NOTSET)

    assert "주일예배" in text
    assert "시 133" in text          # 예배의 부름 reference
    assert "눅 22:14-24" in text     # 말씀 reference
    assert "교회소식" in text


def test_sheet_fixture_exists() -> None:
    sheet = FIXTURES / "sample_sheet.png"
    assert sheet.exists()
    assert sheet.stat().st_size > 0


def test_template_fixture_is_valid_zip() -> None:
    assert zipfile.is_zipfile(FIXTURES / "sample_template.key")


@pytest.mark.local_only
def test_real_template_is_valid_zip(real_template_key: Path) -> None:
    assert zipfile.is_zipfile(real_template_key)
