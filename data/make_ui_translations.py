"""Translate the chat page's interface strings into every supported Indian language (Sarvam), once, offline.

    .venv/bin/python -m data.make_ui_translations
Writes frontend/ui_strings.js (window.UI_STRINGS = {lang: {english: translated}}). The page then switches its whole
interface to the language the applicant speaks or types, with no translation call at run time.
Needs SARVAM_API_KEY. Strings the API returns unchanged or empty fall back to English in the page.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
from backend import voice  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "frontend" / "ui_strings.js"
LANGS = ["hi", "mr", "bn", "ta", "te", "gu", "kn", "ml", "pa", "od"]

STRINGS = [
    # header, loan bar, tabs, stepper
    "Overview", "New check", "Personal", "Home", "Car", "Education", "from",
    "No CIBIL impact", "Reply under 15 s", "PII auto-masked", "Chat", "Quick form",
    "Loan", "About you", "Finances", "Result",
    # chat
    "Namaste, I'm LoanMitra.",
    "Pick a loan below, or just tell me what you need — for example: “I'm 30, salaried, earn 60k a month and need a 5 lakh personal loan for 3 years.”",
    "Type your message…", "Attach a bank statement to verify your income — read in memory, never stored.",
    "No statement handy?", "Try the sample",
    # quick replies
    "Personal Loan", "Home Loan", "Car Loan", "Education Loan", "Yes, confirm", "Change something", "Salaried", "Self-employed",
    "Not working", "Don't know", "No EMIs", "In India", "Abroad", "Compare banks", "Documents needed", "years", "What if",
    # quick form
    "Prefer a form? Fill these in and get your result instantly. Nothing is stored.", "Fetch my details",
    "simulated bureau + Account Aggregator", "Mobile last 4 digits", "I consent to a soft credit check and bank-statement read",
    "Fetch", "Or verify from your bank statement", "live analysis · not stored", "Sample statement", "Loan type",
    "Loan amount (₹)", "Repay over (years)", "Your age", "Employment", "Net monthly income (₹)", "Credit score (CIBIL)",
    "Existing EMIs per month (₹)", "Property value (₹)", "Vehicle on-road price (₹)", "Where is the course?",
    "Parent / guardian monthly income (₹)", "Parent / guardian credit score", "Parent / guardian EMIs per month (₹)",
    "Personal loan", "Home loan", "Car loan", "Education loan", "Self-employed / business", "750 and above (excellent)",
    "700 – 749 (good)", "650 – 699 (fair)", "Below 650", "I don't know", "750 and above", "Check eligibility",
    "Soft check · no CIBIL impact",
    # dashboard
    "Awaiting details", "Your eligible amount", "Share your details and your eligibility appears here.", "strength",
    "Monthly EMI", "Interest", "Tenure", "simulated lender panel", "Try a different amount or tenure", "Loan amount",
    "How to improve your chances", "Rule checks", "Every bank rule we check will appear here, with the numbers.",
    "Your details", "Documents to keep ready", "PII guard on", "Latency", "Language",
    "LoanMitra is a demo built for TCS Technology Day. Rates and rules are illustrative (synthetic policy). Not a loan offer.",
    # dynamic dashboard text
    "Eligible", "Conditionally eligible", "Not eligible right now", "You're eligible for", "You're eligible for up to",
    "Eligible amount today", "Not yet", "Confirm your details", "Collecting details", "One step left",
    "Check the values in the chat and confirm — your result appears right after.", "Still needed:",
    "Move the sliders to see your eligibility change instantly.", "Rules engine", "Not known", "Not employed", "India",
    "Amount", "Age", "Net income / month", "Experience", "Credit score", "Existing EMIs", "Property value", "Vehicle price",
    "Study location", "Co-applicant income", "Co-applicant score", "Co-applicant EMIs",
    "Tenure within product limits", "Age at loan maturity", "Work experience", "Minimum income", "Score margin",
    "Amount within product range", "Loan-to-value", "Collateral", "Repayment capacity (FOIR)", "FOIR margin", "Income multiple cap",
]


# Reviewed corrections where machine translation of a short label was wrong or too literal; brand name kept.
OVERRIDES = {
    "hi": {"Namaste, I'm LoanMitra.": "नमस्ते, मैं LoanMitra हूँ।", "Your eligible amount": "आपकी पात्र राशि", "Eligible": "पात्र",
           "Quick form": "त्वरित फ़ॉर्म", "Yes, confirm": "हाँ, पुष्टि करें", "strength": "मज़बूती", "What if": "अगर",
           "Rules engine": "नियम इंजन", "New check": "नई जाँच", "Overview": "परिचय", "Change something": "कुछ बदलें",
           "Monthly EMI": "मासिक EMI", "Tenure": "अवधि", "Interest": "ब्याज दर", "Loan": "लोन", "Personal Loan": "पर्सनल लोन",
           "Home Loan": "होम लोन", "Car Loan": "कार लोन", "Education Loan": "एजुकेशन लोन", "Personal": "पर्सनल", "Home": "होम",
           "Car": "कार", "Education": "एजुकेशन", "No EMIs": "कोई EMI नहीं", "Conditionally eligible": "शर्तों के साथ पात्र",
           "Not eligible right now": "अभी पात्र नहीं", "You're eligible for": "आप पात्र हैं", "You're eligible for up to": "आप इतनी राशि तक पात्र हैं",
           "Rule checks": "नियम जाँच", "Compare banks": "बैंकों की तुलना करें", "Latency": "समय", "Language": "भाषा"},
    "mr": {"Namaste, I'm LoanMitra.": "नमस्कार, मी LoanMitra आहे.", "Your eligible amount": "तुमची पात्र रक्कम", "Eligible": "पात्र",
           "Quick form": "जलद फॉर्म", "Yes, confirm": "होय, खात्री करा", "strength": "मजबुती", "What if": "जर",
           "Rules engine": "नियम इंजिन", "New check": "नवीन तपासणी", "Overview": "परिचय", "Change something": "काहीतरी बदला",
           "Monthly EMI": "मासिक EMI", "Tenure": "कालावधी", "Interest": "व्याजदर", "Loan": "कर्ज", "Personal Loan": "वैयक्तिक कर्ज",
           "Home Loan": "गृहकर्ज", "Car Loan": "कार कर्ज", "Education Loan": "शैक्षणिक कर्ज", "Personal": "वैयक्तिक", "Home": "गृह",
           "Car": "कार", "Education": "शिक्षण", "No EMIs": "कोणताही EMI नाही", "Conditionally eligible": "अटींसह पात्र",
           "Not eligible right now": "सध्या पात्र नाही", "You're eligible for": "तुम्ही पात्र आहात", "You're eligible for up to": "तुम्ही इतक्या रकमेपर्यंत पात्र आहात",
           "Rule checks": "नियम तपासणी", "Compare banks": "बँकांची तुलना करा", "Latency": "वेळ", "Language": "भाषा",
           "Chat": "चॅट", "Result": "निकाल", "About you": "तुमच्याबद्दल", "Finances": "आर्थिक माहिती", "Awaiting details": "माहितीची प्रतीक्षा",
           "Type your message…": "तुमचा संदेश लिहा…", "years": "वर्षे", "Salaried": "पगारदार", "Self-employed": "स्वयंरोजगार",
           "Check eligibility": "पात्रता तपासा", "Your details": "तुमची माहिती", "Documents needed": "आवश्यक कागदपत्रे"},
}


def _call(text: str, lang: str) -> str:
    """One Sarvam request, retried with backoff on rate limits."""
    for wait in (0, 3, 6, 12, 24):
        time.sleep(wait)
        try:
            return voice._translate_chunk(text, "en", lang).strip()
        except Exception as e:
            if "429" not in str(e):
                print(f"  {lang}: {e}", file=sys.stderr)
                return ""
    return ""


def _batches(items: list[str], limit: int = 700) -> list[list[str]]:
    out, cur, size = [], [], 0
    for s in items:
        if cur and size + len(s) + 1 > limit:
            out.append(cur)
            cur, size = [], 0
        cur.append(s)
        size += len(s) + 1
    return out + ([cur] if cur else [])


def translate_all(lang: str) -> dict[str, str]:
    """Strings go one per line in a few batched requests; a batch whose line count comes back wrong is redone per string."""
    result: dict[str, str] = {}
    for batch in _batches(STRINGS):
        lines = [x.strip() for x in _call("\n".join(batch), lang).split("\n") if x.strip()]
        if len(lines) != len(batch):
            lines = [_call(x, lang) for x in batch]
        result.update({en: t for en, t in zip(batch, lines) if t and t != en})
    result.update(OVERRIDES.get(lang, {}))
    return result


def main() -> None:
    if not voice.available():
        sys.exit("SARVAM_API_KEY is not set")
    assert len(STRINGS) == len(set(STRINGS)), "duplicate strings"
    out = {}
    for lang in LANGS:
        out[lang] = translate_all(lang)
        print(f"{lang}: {len(out[lang])}/{len(STRINGS)}", flush=True)
    OUT.write_text("/* Generated by data/make_ui_translations.py (Sarvam + reviewed overrides). Interface strings only. */\n"
                   f"window.UI_STRINGS = {json.dumps(out, ensure_ascii=False, indent=0)};\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(OUT.parent.parent)}")


if __name__ == "__main__":
    main()
