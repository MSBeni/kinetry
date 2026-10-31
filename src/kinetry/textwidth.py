"""Visual text width for length limits that should mean the same thing in every script.

Limits in plans and the catalog are about how much room text takes on screen, so they count width:
combining marks (Hindi vowel signs, accents written as separate code points, zero-width joiners) count 0,
wide East Asian characters (Chinese, Japanese, Korean, full-width forms) count 2, everything else 1.
"""

from __future__ import annotations

import unicodedata

_ZERO = {"​", "‌", "‍", "⁠", "﻿"}


def text_width(text: str) -> int:
    w = 0
    for ch in text:
        if ch in _ZERO or unicodedata.category(ch).startswith("M"):
            continue
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w
