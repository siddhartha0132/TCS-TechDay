"""Shared parsing of Indian money / number expressions (EN, HI, Hinglish).

Used by the rules engine (to normalise tool/API input) and the extractor (to
find figures in free text), so both agree on what "5 lacs" or "12 LPA" means.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

_DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def normalize_text(text: str) -> str:
    """NFC (folds precomposed ज़ / ड़ into one form) and Devanagari digits -> ASCII."""
    return unicodedata.normalize("NFC", text).translate(_DEV_DIGITS)


def _n(s: str) -> str:
    return unicodedata.normalize("NFC", s)


# unit word -> (multiplier, is_annual)
UNITS: dict[str, tuple[float, bool]] = {_n(k): v for k, v in {
    "crores": (1e7, False), "crore": (1e7, False), "cr": (1e7, False), "karod": (1e7, False), "करोड़": (1e7, False),
    "lpa": (1e5, True),
    "lakhs": (1e5, False), "lakh": (1e5, False), "lacs": (1e5, False), "lac": (1e5, False), "laakh": (1e5, False),
    "लाख": (1e5, False), "l": (1e5, False),
    "thousand": (1e3, False), "hazaar": (1e3, False), "hazar": (1e3, False), "हज़ार": (1e3, False), "हजार": (1e3, False),
    "k": (1e3, False),
}.items()}

_UNIT_ALT = "|".join(re.escape(u) for u in sorted(UNITS, key=len, reverse=True))
NUM = r"\d+(?:,\d+)*(?:\.\d+)?"
# A figure, optional range ("5-6 lakh", "5 to 6 lakh"), optional unit. Latin units must end at a word boundary.
MONEY_RE = re.compile(
    r"(?P<cur>₹|(?<![a-z])rs\.?|(?<![a-z])inr)?\s*(?P<a>" + NUM + r")(?:\s*(?:-|–|to|se)\s*(?P<b>" + NUM + r"))?"
    r"(?:\s*(?P<unit>" + _UNIT_ALT + r")(?![a-z]))?(?:\s*/-)?",
    re.I,
)


@dataclass
class Figure:
    value: float
    start: int
    end: int
    unit: Optional[str]
    currency: bool
    annual: bool
    is_range: bool
    range_high: Optional[float] = None  # upper bound when is_range (value keeps the lower bound)


_WORD_NUMS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
              "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
              "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
              "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
              "ek": 1, "do": 2, "teen": 3, "chaar": 4, "paanch": 5, "che": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10}
_WORD_NUM_RE = re.compile(r"\b(" + "|".join(sorted(_WORD_NUMS, key=len, reverse=True)) + r")\b(?=\s*(?:" +
                          _UNIT_ALT + r")(?![a-z]))", re.I)


def _words_to_digits(text: str) -> str:
    """'five lakh' -> '   5 lakh' (only directly before a unit, so 'take care' never matches).
    Right-padded to the original width so character spans stay valid for callers."""
    return _WORD_NUM_RE.sub(lambda m: str(_WORD_NUMS[m.group(1).lower()]).rjust(len(m.group(1))), text)


def figures(text: str) -> list[Figure]:
    """All numeric mentions in already-normalised text, with spans. Ranges keep the lower bound in
    `value` and expose the upper bound in `range_high` so callers can ask the user to confirm."""
    text = _words_to_digits(text)
    out: list[Figure] = []
    for m in MONEY_RE.finditer(text):
        try:
            val = float(m.group("a").replace(",", ""))
        except ValueError:
            continue
        unit = (m.group("unit") or "").lower() or None
        mult, annual = UNITS.get(unit, (1.0, False)) if unit else (1.0, False)
        val = round(val * mult, 2)  # paise precision; kills 1.1*1e5-style float dust
        if not math.isfinite(val):
            continue
        high = None
        if m.group("b"):
            try:
                high = round(float(m.group("b").replace(",", "")) * mult, 2)
            except ValueError:
                high = None
        out.append(Figure(val, m.start("a") if not m.group("cur") else m.start(), m.end(), unit,
                          bool(m.group("cur")), annual, bool(m.group("b")), high))
    return out


def parse_number(val: object) -> Optional[float]:
    """Parse one value from an API/tool field. Returns None for anything non-finite or unreadable.

    '12,50,000' -> 1250000; '8.5 lakh' -> 850000; '2 crores' -> 2e7; '₹45,000 per month' -> 45000;
    '12 LPA' -> 100000 (monthly); 'around 680' -> 680; 'nan' / 'inf' / 'abc' -> None.
    """
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        v = float(val)
        return v if math.isfinite(v) else None
    s = normalize_text(str(val)).strip().lower()
    if not s or re.search(r"\b(nan|inf|infinity)\b|\d[x_]|_\d", s):  # NaN/inf, hex, 1_000 style -> reject
        return None
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?e[-+]?\d+", s):  # scientific notation from integrations
        v = float(s)
        return v if math.isfinite(v) else None
    negative = bool(re.match(r"^\s*-\s*(?:₹|rs\.?\s*)?\d", s))
    figs = figures(s)
    if not figs:
        return None
    f = figs[0]
    v = f.value / 12 if (f.annual or re.search(r"per annum|p\.?a\.?\b|a year|per year|yearly|annual", s)) else f.value
    v = round(v, 2)
    return -v if negative else v
