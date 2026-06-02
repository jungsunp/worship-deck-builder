"""Attach the transcribed band-sheet medley to its worship-order slot.

The bulletin lists no opening-worship song titles — the opening 찬양 row's content is
just the worship band's name (e.g. 마라나타), and the actual songs live only on the
Kakao band lead sheet that ``transcribe()`` reads. So there is nothing to title-match:
the whole medley maps wholesale to the single opening congregational 찬양 slot. The
*other* 찬양 row in the order is the 성가대 (choir) song, which is pasted raw text
(#53), not band-sheet content — it carries 성가대 as its leader, which is how we tell
the two 찬양 rows apart.
"""

from __future__ import annotations

from worship_deck.lyrics.transcribe import Song


def _is_opening_worship(row: dict) -> bool:
    """True for the opening congregational 찬양 row (not the 성가대 choir row)."""
    if row.get("part", "").replace(" ", "") != "찬양":
        return False
    return "성가대" not in (row.get("title", "") + row.get("leader", ""))


def assign_worship_songs(worship_order: list[dict], songs: list[Song]) -> list[dict]:
    """Attach the band-sheet medley (ordered) to the opening 찬양 slot.

    Sets ``row["songs"]`` on the first opening congregational 찬양 row; the row's
    ``title`` stays the band name (the review UI displays ``songs``). If no such row
    exists the order is returned unchanged (the operator catches it in review).
    """
    for row in worship_order:
        if _is_opening_worship(row):
            row["songs"] = list(songs)
            break
    return worship_order
