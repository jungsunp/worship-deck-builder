"""Fixed-wording deck content for the ProPresenter generator (v3 migration, #171).

**Skeleton only (#171).** The divider labels are final; the liturgy texts are intentionally
left empty to be sourced (not invented) in #172/#178 — see below.

These are the parts of the deck that don't come from the weekly ``ServiceData``: the
fixed-wording liturgy (사도신경 creed, 주기도문 Lord's Prayer) and the section divider headings.
``build.fill_liturgy`` styles them via the same ``section_divider`` / ``liturgy`` style-kit
prototypes as everything else. Non-sensitive (no member names/amounts) — safe to commit.
"""

from __future__ import annotations

# Section divider headings, matching the church's wording (the same landmark text
# keynote/anchors.py detects; see config/slide_map.yaml). Used as CueGroup labels + divider slides.
DIVIDER_LABELS = {
    "call_to_worship": "예배의 부름",
    "worship_songs": "찬양",
    "confession_song": "고백의 찬양",
    "apostles_creed": "사도신경",
    "choir_song": "성가대 찬양",
    "offering_hymn": "봉 헌",
    "announcements": "교회 소식",
    "sermon": "말씀",
    "lords_prayer": "주기도문",
}

# Fixed liturgy texts. Deliberately EMPTY: there are multiple Korean translations of each
# (사도신경 old/new; 주기도문 wording), so these must be copied from the church's actual current
# deck — not invented here. #172/#178: dump the 사도신경 / 주기도문 slide text from the existing
# master.key template (see memory "Decode .key slide text": osascript per-slide dump) and paste
# the exact wording, one paragraph per slide-chunk, below.
APOSTLES_CREED: list[str] = []   # 사도신경 — fill from the template deck (#172/#178)
LORDS_PRAYER: list[str] = []     # 주기도문 — fill from the template deck (#172/#178)
