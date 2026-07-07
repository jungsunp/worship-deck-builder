"""RTF text substitution for ProPresenter slide text (v3 migration, #171).

**Skeleton only (#171).** #172 implements the bodies.

A ProPresenter text element stores its visible run as ``rtf_data`` — RTF bytes that carry
both the characters *and* the baked styling (font/size/color/paragraph). To reuse a style-kit
prototype's look we must change only the characters, keeping every surrounding RTF control
word intact. The prototype's editable run holds a placeholder token (e.g. ``{{TEXT}}``); we
substitute the token's RTF-escaped replacement in place.

The one real subtlety (flagged as the main #172 risk): Korean is non-ASCII, so it must be
emitted as RTF ``\\uN?`` unicode escapes — a raw UTF-8 byte replace (as ``roundtrip.hello_world``
does for ASCII ``Hello World``) corrupts Hangul. ``_rtf_escape`` owns that.
"""

from __future__ import annotations

from . import pb  # noqa: F401 -- side effect: puts pb/ on sys.path for the bare *_pb2 imports

import graphicsData_pb2


def set_placeholder(element: graphicsData_pb2.Graphics.Element, token: str, text: str) -> None:
    """Replace ``token`` inside ``element``'s ``text.rtf_data`` with ``text`` (RTF-escaped),
    preserving all surrounding RTF control words so the baked styling survives. #172."""
    raise NotImplementedError("#172: placeholder substitution in rtf_data")


def set_text(element: graphicsData_pb2.Graphics.Element, text: str) -> None:
    """Set ``element``'s single visible run to ``text``, keeping the run's existing styling.

    For multi-line content (lyric slides, verse bodies) ``text`` may contain newlines, mapped
    to RTF paragraph breaks. #172.
    """
    raise NotImplementedError("#172: rewrite the run text, keep styling")


def _rtf_escape(text: str) -> str:
    """Escape ``text`` for an RTF run: ``\\``/``{``/``}`` escaped and every non-ASCII code point
    (all Hangul) emitted as ``\\uN?``. #172."""
    raise NotImplementedError("#172: RTF unicode escaping (Korean)")
