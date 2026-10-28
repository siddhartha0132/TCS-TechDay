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


def figures(text: str) -> list[Figure]:
    """All numeric mentions in already-normalised text, with spans. Ranges keep the lower bound."""
    out: list[Figure] = []
    for m in MONEY_RE.finditer(text):
        try:
            val = float(m.group("a").replace(",", ""))
        except ValueError:
            continue
        unit = (m.group("unit") or "").lower() or None
        mult, annual = UNITS.get(unit, (1.0, False)) if unit else (1.0, False)
        val *= mult
        if not math.isfinite(val):
            continue
        out.append(Figure(val, m.start("a") if not m.group("cur") else m.start(), m.end(), unit,
                          bool(m.group("cur")), annual, bool(m.group("b"))))
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
    return -v if negative else v
