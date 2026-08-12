"""Regenerate src/worship_deck/bible/data/krv.json (개역한글) from bolls.life.

Why this script exists
----------------------
The original bundled dataset came from scrollmapper/bible_databases
(`formats/json/KorRV.json`). That file is a **Baptist redaction**: it writes
침례 wherever 개역한글 reads 세례 (101 occurrences). Our church is Presbyterian,
so that text was wrong on every baptism verse. The same corrupted module is
mirrored by getbible.net (`/v2/korean`), so neither source is usable.

bolls.life's KRV is the authentic 대한성서공회 개역한글 text: it reads 세례, keeps
the original 1961 orthography (찬양할찌어다, 일찌기, 파숫군 — which is what the
church's own master.key template uses), and does not carry the 어호와/죄우 typos
that the scrollmapper copy had.

The output keeps the schema and book-name spellings of the original file so
`kkrv.py` (including its Roman-numeral `_NAME_FIX`) needs no changes.

Usage:
    python scripts/fetch_krv.py
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

SOURCE_URL = "https://bolls.life/static/translations/KRV.json"
OUT_PATH = Path(__file__).resolve().parents[1] / "src/worship_deck/bible/data/krv.json"

# bolls numbers books 1-66; these are the names the existing krv.json uses
# (Roman numerals + "Revelation of John"), kept so kkrv.py._NAME_FIX still applies.
BOOK_NAMES = [
    "Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy", "Joshua", "Judges",
    "Ruth", "I Samuel", "II Samuel", "I Kings", "II Kings", "I Chronicles",
    "II Chronicles", "Ezra", "Nehemiah", "Esther", "Job", "Psalms", "Proverbs",
    "Ecclesiastes", "Song of Solomon", "Isaiah", "Jeremiah", "Lamentations",
    "Ezekiel", "Daniel", "Hosea", "Joel", "Amos", "Obadiah", "Jonah", "Micah",
    "Nahum", "Habakkuk", "Zephaniah", "Haggai", "Zechariah", "Malachi", "Matthew",
    "Mark", "Luke", "John", "Acts", "Romans", "I Corinthians", "II Corinthians",
    "Galatians", "Ephesians", "Philippians", "Colossians", "I Thessalonians",
    "II Thessalonians", "I Timothy", "II Timothy", "Titus", "Philemon", "Hebrews",
    "James", "I Peter", "II Peter", "I John", "II John", "III John", "Jude",
    "Revelation of John",
]


def main() -> None:
    print(f"downloading {SOURCE_URL} ...")
    with urllib.request.urlopen(SOURCE_URL) as resp:
        rows = json.loads(resp.read().decode("utf-8"))
    print(f"  {len(rows)} verses")

    # group into books -> chapters -> verses, preserving canonical order
    grouped: dict[int, dict[int, dict[int, str]]] = {}
    for row in rows:
        text = row["text"].strip()
        if not text:
            continue
        grouped.setdefault(row["book"], {}).setdefault(row["chapter"], {})[row["verse"]] = text

    if sorted(grouped) != list(range(1, 67)):
        raise SystemExit(f"expected books 1-66, got {sorted(grouped)}")

    out = {
        "translation": "개역한글 (Korean Revised Version, 1961) — 대한성서공회",
        "_source": SOURCE_URL,
        "_note": "Presbyterian-correct baptism wording (세례). Regenerate: scripts/fetch_krv.py",
        "books": [
            {
                "name": BOOK_NAMES[bn - 1],
                "chapters": [
                    {
                        "chapter": cn,
                        "verses": [
                            {"verse": vn, "text": verses[vn]} for vn in sorted(verses)
                        ],
                    }
                    for cn, verses in sorted(grouped[bn].items())
                ],
            }
            for bn in sorted(grouped)
        ],
    }

    total = sum(len(c["verses"]) for b in out["books"] for c in b["chapters"])
    flat = "".join(v["text"] for b in out["books"] for c in b["chapters"] for v in c["verses"])
    if "침례" in flat:
        raise SystemExit("refusing to write: source contains 침례")
    print(f"  {len(out['books'])} books, {total} verses, 세례 x{flat.count('세례')}")

    OUT_PATH.write_text(
        json.dumps(out, ensure_ascii=False, indent=4) + "\n", encoding="utf-8"
    )
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
