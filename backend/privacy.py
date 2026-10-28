"""PII masking applied to every message *before* it reaches the LLM or logs.

Nothing is persisted: sessions live in memory and the masked text is what gets
stored in the conversation history.
"""
from __future__ import annotations

import re

PATTERNS: list[tuple[str, re.Pattern]] = [
    ("PAN", re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")),
    ("Aadhaar", re.compile(r"\b[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}\b")),
    ("phone", re.compile(r"(?<!\d)(?:\+91[\s-]?|0)?[6-9]\d{9}(?!\d)")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("account", re.compile(r"\b(?:a/?c|acct|account)\s*(?:no\.?|number)?\s*:?\s*\d{9,18}\b", re.I)),
    ("card", re.compile(r"\b(?:\d{4}[\s-]?){3}\d{4}\b")),
]


def mask_pii(text: str) -> tuple[str, list[str]]:
    """Return (masked_text, [kinds of PII found])."""
    found: list[str] = []
    for kind, pat in PATTERNS:
        if pat.search(text):
            found.append(kind)
            text = pat.sub(f"[{kind} masked]", text)
    return text, found
