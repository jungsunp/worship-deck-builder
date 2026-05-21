"""Parse the weekly bulletin PDF into structured service data.

Extracts: service date, worship order (song titles + who leads each part),
announcements (교회소식), Bible references for 예배의 부름 and 말씀, and sermon title.
The bulletin layout is stable week to week, so text extraction is reliable.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ServiceData:
    date: str = ""
    worship_order: list[dict] = field(default_factory=list)
    announcements: list[str] = field(default_factory=list)
    call_to_worship_ref: str = ""
    sermon_title: str = ""
    sermon_ref: str = ""


def parse(pdf_path: str) -> ServiceData:
    """Parse a bulletin PDF into ServiceData. (pdfplumber)"""
    raise NotImplementedError
