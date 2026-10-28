"""PII masking applied to every message *before* it reaches the LLM, history or logs.

Two goals pull against each other: catch identifiers in any common format, and
never destroy legitimate rupee figures ("a home loan of 9500000000 rupees").
So bare digit runs are only masked when they look like an identifier: a
checksum passes (Luhn for cards, Verhoeff for Aadhaar), an identifier keyword
is nearby, or they are written in the identifier's usual grouping, and never
when money context surrounds them.
"""
from __future__ import annotations

import re

MONEY_CONTEXT = re.compile(
    r"(?:₹|\brs\.?|\binr|\brupees?|\blakh|\blac|\bcrore|\bcr\b|\bloan|\bamount|\bsalary|\bincome|\bworth|\bprice|\bcost|"
    r"\bvalue|\bemi|\bborrow|\bneed|\bearn|\bpay)", re.I)
ID_KEYWORDS = {
    "phone": re.compile(r"\b(?:phone|mobile|mob|cell|call|contact|whats\s?app|number|no\.?)\b|फ़ोन|फोन|मोबाइल|नंबर", re.I),
    "Aadhaar": re.compile(r"\b(?:aadhaar|aadhar|adhar|uid|uidai)\b|आधार", re.I),
    "card": re.compile(r"\b(?:card|credit card|debit card|cc)\b", re.I),
    "account": re.compile(r"\b(?:a/?c|acct|account|ifsc)\b|खाता", re.I),
    "doc": re.compile(r"\b(?:passport|dl|driving|licen[cs]e|voter|epic|dob|birth|born)\b|पासपोर्ट|लाइसेंस|मतदाता|जन्म", re.I),
}

PAN = re.compile(r"\b[a-z]{5}\s?[0-9]{4}\s?[a-z]\b", re.I)
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
UPI = re.compile(r"\b[\w.\-]{2,30}@[a-zA-Z]{2,20}\b")  # name@okhdfc (emails carry a dotted domain and are masked first)
IFSC = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")  # strict ABCD0123456 format needs no keyword
VOTER = re.compile(r"\b[A-Z]{3}[0-9]{7}\b")
PASSPORT = re.compile(r"\b[A-Z][0-9]{7}\b")
DL = re.compile(r"\b(?:[A-Z]{2}\d{2}[\s-]?\d{4}[\s-]?\d{4,7}|[A-Z]{2}\d{13})\b")
DOB = re.compile(r"\b\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}\b")
PHONE_PREFIXED = re.compile(r"(?:\+|\b00)91[\s-]*[6-9]\d{4}[\s-]*\d{5}\b|\b0[6-9]\d{4}[\s-]*\d{5}\b")
PHONE_GROUPED = re.compile(r"\b[6-9]\d{4}[\s-]\d{5}\b|\b[6-9]\d{2}[\s-]\d{3}[\s-]\d{4}\b")
PHONE_BARE = re.compile(r"(?<![\d.,])[6-9]\d{9}(?![\d.,])")
AADHAAR_GROUPED = re.compile(r"\b[2-9]\d{3}[\s-]\d{4}[\s-]\d{4}\b")
AADHAAR_BARE = re.compile(r"(?<![\d.,])[2-9]\d{11}(?![\d.,])")
CARD = re.compile(r"(?<![\d.,])(?:\d{4}[\s-]?){3}\d{4}(?![\d.,])")
ACCOUNT = re.compile(r"\b(?:a/?c|acct|account)\s*(?:no\.?|number)?\s*[:#-]?\s*\d{9,18}\b", re.I)
# Bare 14–18 digit runs with no money context are identifiers, not chat amounts (which carry
# units or ₹ at that size). Shorter bare runs still need an account keyword (ACCOUNT above).
ACCOUNT_BARE = re.compile(r"(?<![\d.,])\d{14,18}(?![\d.,])")

_DEV_FOLD = str.maketrans("०१२३४५६७८९", "0123456789")

# Verhoeff tables (Aadhaar check digit)
_D = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6], [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
      [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1], [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
      [8, 7, 6, 5, 9, 3, 2, 1, 0, 4], [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_P = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2], [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
      [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1], [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]


def _verhoeff_ok(num: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(num)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def _luhn_ok(num: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(num)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _near(text: str, start: int, end: int, pat: re.Pattern, before: int = 30, after: int = 15) -> bool:
    return bool(pat.search(text[max(0, start - before):start] + " " + text[end:end + after]))


def _mask_folded_digits(text: str, found: list[str]) -> str:
    """Mask phone/Aadhaar written in Devanagari digits (९८७६५४३२१०). The fold is a 1:1
    character mapping, so spans found in the folded copy apply to the original."""
    folded = text.translate(_DEV_FOLD)
    if folded == text:
        return text

    def money_at(s: int, e: int) -> bool:
        return _near(text, s, e, MONEY_CONTEXT, 25, 12)

    def kw_at(s: int, e: int, kind: str) -> bool:
        return _near(text, s, e, ID_KEYWORDS[kind])

    hits: list[tuple[int, int, str]] = []
    for m in PHONE_PREFIXED.finditer(folded):
        hits.append((m.start(), m.end(), "phone"))
    for m in PHONE_GROUPED.finditer(folded):
        if not (money_at(m.start(), m.end()) and not kw_at(m.start(), m.end(), "phone")):
            hits.append((m.start(), m.end(), "phone"))
    for m in PHONE_BARE.finditer(folded):
        if not (money_at(m.start(), m.end()) and not kw_at(m.start(), m.end(), "phone")):
            hits.append((m.start(), m.end(), "phone"))
    for m in AADHAAR_GROUPED.finditer(folded):
        hits.append((m.start(), m.end(), "Aadhaar"))
    for m in AADHAAR_BARE.finditer(folded):
        if kw_at(m.start(), m.end(), "Aadhaar") or \
                (not money_at(m.start(), m.end()) and _verhoeff_ok(m.group(0))):
            hits.append((m.start(), m.end(), "Aadhaar"))
    claimed: list[tuple[int, int]] = []
    for s, e, kind in sorted(hits, reverse=True):
        if any(s < ce and e > cs for cs, ce in claimed):
            continue
        claimed.append((s, e))
        text = text[:s] + f"[{kind} masked]" + text[e:]
        if kind not in found:
            found.append(kind)
    return text


def mask_pii(text: str) -> tuple[str, list[str]]:
    """Return (masked_text, [kinds of PII found])."""
    found: list[str] = []
    text = _mask_folded_digits(text, found)

    def sub(pattern: re.Pattern, kind: str, s: str, keep=None) -> str:
        def repl(m: re.Match) -> str:
            if keep and keep(m, s):
                return m.group(0)
            if kind not in found:
                found.append(kind)
            return f"[{kind} masked]"
        return pattern.sub(repl, s)

    digits = lambda m: re.sub(r"\D", "", m.group(0))  # noqa: E731
    money = lambda m, s: _near(s, m.start(), m.end(), MONEY_CONTEXT, 25, 12)  # noqa: E731

    text = sub(EMAIL, "email", text)
    text = sub(PAN, "PAN", text, keep=lambda m, s: not re.search(r"\d{4}", m.group(0)))
    text = sub(UPI, "upi", text)
    text = sub(IFSC, "ifsc", text)
    text = sub(VOTER, "voter id", text, keep=money)
    text = sub(DL, "driving licence", text, keep=money)
    text = sub(PASSPORT, "passport", text,
               keep=lambda m, s: not _near(s, m.start(), m.end(), ID_KEYWORDS["doc"]))
    text = sub(DOB, "dob", text,
               keep=lambda m, s: not _near(s, m.start(), m.end(), ID_KEYWORDS["doc"]))
    text = sub(ACCOUNT, "account", text)
    text = sub(CARD, "card", text,
               keep=lambda m, s: not (_luhn_ok(digits(m)) or _near(s, m.start(), m.end(), ID_KEYWORDS["card"])) or
               (money(m, s) and not _near(s, m.start(), m.end(), ID_KEYWORDS["card"])))
    text = sub(ACCOUNT_BARE, "account", text, keep=money)
    text = sub(AADHAAR_GROUPED, "Aadhaar", text)
    text = sub(AADHAAR_BARE, "Aadhaar", text,
               keep=lambda m, s: not _near(s, m.start(), m.end(), ID_KEYWORDS["Aadhaar"]) and
               (money(m, s) or not _verhoeff_ok(m.group(0))))
    text = sub(PHONE_PREFIXED, "phone", text)
    text = sub(PHONE_GROUPED, "phone", text, keep=lambda m, s: money(m, s) and not _near(s, m.start(), m.end(), ID_KEYWORDS["phone"]))
    text = sub(PHONE_BARE, "phone", text, keep=lambda m, s: money(m, s) and not _near(s, m.start(), m.end(), ID_KEYWORDS["phone"]))
    return text, found
