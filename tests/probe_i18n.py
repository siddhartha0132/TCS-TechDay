"""Language detection, templated replies, and localized verdict summaries."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _setup  # noqa: F401,E402

from backend import i18n  # noqa: E402
from backend.rules import evaluate  # noqa: E402

fails = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    fails += not ok
    print(f"{'OK  ' if ok else 'FAIL'} {name} {detail}")


DETECT = [  # (preference, expected)
    ("auto", "I need a personal loan of 5 lakh", "en"),
    ("auto", "mujhe 5 lakh ka loan chahiye, salary 60 hazaar hai", "hinglish"),
    ("auto", "मुझे 5 लाख का लोन चाहिए", "hi"),
    ("auto", "kitna?", "hinglish"),
    ("auto", "chahiye", "hinglish"),
    ("auto", "meet me at noon aur midnight", "en"),
    ("auto", "I said toh loudly yesterday", "en"),
    ("auto", "hai mujhe", "hinglish"),
    ("hi", "I need a loan", "hi"),
    ("en", "मुझे लोन चाहिए", "en"),
]
for pref, text, want in DETECT:
    got = i18n.detect_language(text, pref)
    check(f"detect {text[:32]!r}", got == want, f"got {got}")

check("ask falls back to en", "borrow" in i18n.ask_for("fr", "loan_amount").lower())
check("hi ask", "लोन" in i18n.ask_for("hi", "loan_amount"))
check("hinglish ask", "kitna" in i18n.ask_for("hinglish", "loan_amount").lower())

prof = {"loan_type": "personal", "loan_amount": 600000, "tenure_years": 4, "age": 29,
        "monthly_income": 65000, "employment_type": "salaried", "credit_score": 760, "existing_emi": 0}
check("en summary unchanged", evaluate(prof).summary.startswith("You are eligible for a Personal Loan"))
check("hi summary", "पात्र" in evaluate(prof, "hi").summary)
check("hinglish summary", "eligible hain" in evaluate(prof, "hinglish").summary)
check("bad lang falls back", evaluate(prof, "fr").summary.startswith("You are eligible"))
check("hi conditional", "पात्र" in evaluate(dict(prof, loan_amount=5000000), "hi").summary)

ev = evaluate(dict(prof, credit_score=500, monthly_income=20000)).as_dict()
r = i18n.render_evaluation("en", ev, [])
check("n-more count shown", "+2 more in the side panel." in r, r.splitlines()[-2:])
r_hi = i18n.render_evaluation("hi", ev, [])
check("hi n-more count", "साइड पैनल" in r_hi)

print(f"i18n_probe: {fails} failing")
raise SystemExit(1 if fails else 0)
