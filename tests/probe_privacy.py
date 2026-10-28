"""PII masking: identifiers in every common format are masked; legitimate rupee figures survive."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _setup  # noqa: F401,E402

from backend.privacy import mask_pii  # noqa: E402

CASES = [  # (text, expected kinds, substring that must survive)
    ("my pan is abcde1234f", ["PAN"], None),
    ("PAN: ABCDE1234F", ["PAN"], None),
    ("call me on +91 98765 43210", ["phone"], None),
    ("my number is 9876543210", ["phone"], None),
    ("9876543210", ["phone"], None),
    ("whatsapp 98765-43210", ["phone"], None),
    ("aadhaar 2345 6789 0123", ["Aadhaar"], None),
    ("my aadhar is 234567890123", ["Aadhaar"], None),
    ("card 4111 1111 1111 1111", ["card"], None),
    ("mail me at a.b+c@bank.co.in", ["email"], None),
    ("account no 123456789012", ["account"], None),
    ("I want a home loan of 9500000000 rupees", [], "9500000000"),
    ("property worth 1234123412341234", [], "1234123412341234"),
    ("loan amount 234567890123", [], "234567890123"),
    ("salary 65,000 per month, need 6 lakh", [], "65,000"),
    ("need 25,00,000 for 20 years", [], "25,00,000"),
    ("I'm 29, salaried, 65000 pm, cibil 760", [], "65000"),
]

fails = 0
for text, kinds, keep in CASES:
    out, found = mask_pii(text)
    if sorted(found) != sorted(kinds) or (keep is not None and keep not in out):
        fails += 1
        print(f"FAIL {text!r} -> {out!r} {found} (expected {kinds})")
print(f"privacy_probe: {len(CASES)} cases, {fails} failing")
raise SystemExit(1 if fails else 0)
