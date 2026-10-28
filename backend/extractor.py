"""Heuristic (regex) extraction of applicant facts from free text.

Used by the deterministic agent when no LLM key is configured, and by the eval
harness as a baseline. Understands English, Hinglish and Devanagari number words.
"""
from __future__ import annotations

import re
from typing import Any, Optional

NUM = r"(\d+(?:,\d+)*(?:\.\d+)?)"
UNIT = r"\s*(crores?|cr\b|karod|करोड़|lakhs?|lacs?|laakh|लाख|l\b|thousand|hazaar|hazar|हज़ार|हजार|k\b)?"
MONEY = re.compile(r"(?:₹|rs\.?|inr)?\s*" + NUM + UNIT, re.I)

UNIT_MULT = {"crore": 1e7, "crores": 1e7, "cr": 1e7, "karod": 1e7, "करोड़": 1e7,
             "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "laakh": 1e5, "लाख": 1e5, "l": 1e5,
             "thousand": 1e3, "hazaar": 1e3, "hazar": 1e3, "हज़ार": 1e3, "हजार": 1e3, "k": 1e3}

LOAN_TYPE_WORDS = {
    "personal": ["personal loan", "personal", "pl ", "wedding", "shaadi", "medical", "travel", "व्यक्तिगत", "पर्सनल"],
    "home": ["home loan", "house", "home", "flat", "property", "ghar", "makaan", "घर", "होम", "मकान", "mortgage", "housing", "apartment"],
    "auto": ["car loan", "car", "vehicle", "gaadi", "gadi", "गाड़ी", "कार", "auto loan", "bike", "two wheeler", "two-wheeler", "suv"],
    "education": ["education loan", "education", "study", "studies", "padhai", "पढ़ाई", "एजुकेशन", "शिक्षा", "college", "university", "course", "mba", "ms ", "masters", "student"],
}

YES = ("yes", "yeah", "yep", "haan", "ha", "हाँ", "हां", "ji", "sure", "correct", "right", "abroad", "foreign", "videsh", "विदेश", "overseas",
       "usa", "us", "uk", "canada", "australia", "germany", "europe", "london", "america")
NO = ("no", "nope", "nahi", "nahin", "nai", "नहीं", "none", "nil", "zero", "0", "india", "bharat", "भारत", "domestic", "local")


def parse_money(num: str, unit: Optional[str]) -> float:
    val = float(num.replace(",", ""))
    if unit:
        val *= UNIT_MULT.get(unit.lower().strip(), 1)
    return val


def _money_near(text: str, keywords: list[str], window: int = 45, after_only: bool = False) -> Optional[float]:
    """Find a money figure within `window` chars of any keyword."""
    for kw in keywords:
        for m in re.finditer(kw, text, re.I):
            lo = m.start() if after_only else max(0, m.start() - window)
            hi = min(len(text), m.end() + window)
            seg = text[lo:hi]
            candidates = []
            for mm in MONEY.finditer(seg):
                # distance from keyword to number
                pos = lo + mm.start()
                dist = abs(pos - m.start())
                candidates.append((dist, parse_money(mm.group(1), mm.group(2))))
            if candidates:
                candidates.sort()
                return candidates[0][1]
    return None


EXPLICIT_LOAN = re.compile(r"\b(personal|home|housing|house|car|auto|vehicle|education|student|study)\s*(?:loan|लोन)", re.I)
LOAN_ALIAS = {"housing": "home", "house": "home", "car": "auto", "vehicle": "auto", "student": "education", "study": "education"}


def detect_loan_type(text: str) -> Optional[str]:
    t = " " + text.lower().replace("take-home", "takehome").replace("take home", "takehome") + " "
    m = EXPLICIT_LOAN.search(t)
    if m:
        w = m.group(1).lower()
        return LOAN_ALIAS.get(w, w)
    best, best_pos = None, 10**9
    for ltype, words in LOAN_TYPE_WORDS.items():
        for w in words:
            pos = t.find(" " + w.strip() + " ") if w.strip().isalpha() and w.isascii() else t.find(w)
            if pos != -1 and pos < best_pos:
                best, best_pos = ltype, pos
    return best


def extract(text: str, expected_field: Optional[str] = None, loan_type: Optional[str] = None) -> dict[str, Any]:
    """Pull whatever applicant facts are present in `text`.

    `expected_field` is the slot the bot just asked for; a bare number or a
    yes/no answer is assigned to it.
    """
    out: dict[str, Any] = {}
    t = text.strip()
    tl = t.lower()

    # --- Direct answer to the question just asked
    if expected_field:
        if expected_field == "loan_type":
            lt = detect_loan_type(tl)
            if lt:
                out["loan_type"] = lt
                return out
        elif expected_field == "employment_type":
            et = detect_employment(tl)
            if et:
                out["employment_type"] = et
                return out
        elif expected_field == "study_abroad":
            if any(w in tl.split() or w in tl for w in YES):
                out["study_abroad"] = True
                return out
            if any(w in tl.split() or w in tl for w in NO):
                out["study_abroad"] = False
                return out
        elif expected_field in ("existing_emi", "co_applicant_existing_emi") and any(w == tl or w in tl.split() for w in NO):
            out[expected_field] = 0.0
            return out
        else:
            nums = list(MONEY.finditer(t))
            # Only treat as a direct answer when the message is basically just a number
            if len(nums) == 1 and len(re.sub(r"[\d,.\s₹]|rs|lakh|lac|cr|crore|k|years?|yrs?|months?|saal|per month|pm", "", tl)) < 12:
                val = parse_money(nums[0].group(1), nums[0].group(2))
                if expected_field == "tenure_years" and re.search(r"month|mahin", tl):
                    val = val / 12
                out[expected_field] = val
                return out

    # --- Free-form sentence: pull everything we can
    lt = detect_loan_type(tl) or loan_type
    if detect_loan_type(tl):
        out["loan_type"] = detect_loan_type(tl)

    et = detect_employment(tl)
    if et:
        out["employment_type"] = et

    if re.search(r"\b(abroad|foreign|overseas|videsh|विदेश|usa|uk|canada|australia|germany|london|america)\b", tl):
        out["study_abroad"] = True
    elif re.search(r"\b(in india|india me|india mein|bharat|भारत)\b", tl):
        out["study_abroad"] = False

    work = t
    # Age: "32 years old", "age 32", "I am 32", "32 saal ka"
    m = (re.search(r"(\d{2})\s*(?:years?|yrs?|saal|साल)\s*(?:old|ka|ki|का|की)", work, re.I)
         or re.search(r"\b(?:age|aged|umar|umr|उम्र)\s*(?:is|of|:)?\s*(\d{2})", work, re.I)
         or re.search(r"\b(?:i am|i'm|im|main|मैं)\s*(\d{2})\b(?!,\d)(?!\s*(?:lakh|lac|k\b|l\b|cr|thousand|hazaar))", work, re.I))
    if m and 17 <= int(m.group(1)) <= 80:
        out["age"] = float(m.group(1))
        work = work[: m.start()] + " " * (m.end() - m.start()) + work[m.end():]

    # Credit score: 3-digit number 300-900 near "score/cibil"
    m = re.search(r"(?:cibil|credit score|score|क्रेडिट स्कोर|सिबिल)\D{0,20}?(\d{3})\b", work, re.I) or \
        re.search(r"\b([3-8]\d{2}|900)\s*(?:cibil|credit score|score)", work, re.I)
    if m and 300 <= int(m.group(1)) <= 900:
        key = "co_applicant_credit_score" if re.search(r"(father|mother|parent|co[- ]?applicant|papa|mummy|guardian|पिता|माता)[^.]{0,40}" + re.escape(m.group(0)[:10]), work, re.I) else "credit_score"
        out[key] = float(m.group(1))
        work = work[: m.start()] + " " * (m.end() - m.start()) + work[m.end():]

    # Tenure: "for 5 years", "20 saal", "60 months"
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(years?|yrs?|saal|साल|months?|mahine|महीने)\b", work, re.I):
        val = float(m.group(1))
        if m.group(2).lower().startswith(("month", "mahin", "महीने")):
            val = val / 12
        if 0.5 <= val <= 35:
            out["tenure_years"] = val
            work = work[: m.start()] + " " * (m.end() - m.start()) + work[m.end():]
            break

    # Co-applicant / parent income (education)
    v = _money_near(work, [r"(?:father|mother|parent|papa|mummy|guardian|co[- ]?applicant|पिता|माता|dad|mom|husband|wife|पति|पत्नी)(?:'s|s'|\s*ki|\s*ka|\s*की|\s*का)?\s*(?:net\s*|monthly\s*)?(?:income|salary|earn\w*|kamat\w*|कमा\w*|आय|वेतन)",
                          r"co[- ]?applicant"])
    if v is not None:
        out["co_applicant_income"] = v
    # Applicant income (skip if the only income phrase belongs to co-applicant)
    if v is None or re.search(r"\b(my|mera|meri|मेरी|मेरा|i earn|i make)\b", work, re.I):
        v2 = _money_near(work, [r"\b(?:my|mera|meri|मेरी|मेरा)?\s*(?:net\s*|monthly\s*|take[- ]home\s*)?(?:salary|income|earn\w*|making|kamata|kamati|कमा\w*|आय|वेतन|सैलरी|सेलरी|तनख्वाह)", r"take[- ]?home", r"\bper month\b", r"\bpm\b", r"\ba month\b"])
        if v2 is not None and v2 != v:
            out["monthly_income"] = v2

    # Existing EMI
    if re.search(r"(?:^|\s)(no|nahi|nahin|नहीं|koi|कोई|zero|without)\s[^.।]{0,25}(emi|loan|loans|obligation|dues|ईएमआई|लोन|कर्ज)", work, re.I) or \
       re.search(r"(emi|loans?|ईएमआई|लोन|कर्ज)[^.।]{0,15}(nil|zero|none|nahi|nahin|नहीं)", work, re.I):
        out["existing_emi"] = 0.0
    else:
        v = _money_near(work, [r"(?:existing|current|other|already|pehle se|paying|pay)\s*(?:an?\s*)?(?:emis?|loans?)", r"\bemis?\b", r"ईएमआई"])
        if v is not None:
            out["existing_emi"] = v

    # Asset values
    v = _money_near(work, [r"(?<!take-)(?<!take )(?:property|flat|house|home|ghar|मकान|घर|संपत्ति)(?!\s*loan)\s*(?:is\s*)?(?:ki\s*|की\s*)?(?:worth|value|valued|cost\w*|price|keemat|kimat|कीमत|of|ka|का)",
                           r"(?:worth|valued at|costing|costs?|keemat|कीमत)",
                           r"(?<!take-)(?<!take )(?:property|flat|house|संपत्ति)(?!\s*loan)\s*(?:of\s*)?(?=(?:₹|rs\.?)?\s*\d)"])
    if v is not None and (lt == "home" or "property" in tl or "flat" in tl):
        out["property_value"] = v
    v = _money_near(work, [r"on[- ]road(?:\s*price)?", r"ex[- ]showroom",
                          r"(?:car|vehicle|bike|gaadi|gadi|गाड़ी)(?!\s*loan)\s*(?:is\s*)?(?:ki\s*|की\s*)?(?:worth|value|valued|cost\w*|price|कीमत|ka|का)"])
    if v is not None and lt == "auto":
        out["vehicle_price"] = v

    # Loan amount: nearest money to "loan/need/want/borrow/amount"
    v = _money_near(work, [r"(?:loan|borrow|need|want|require|looking for|amount|chahiye|चाहिए|लोन)\s*(?:of|for|about|around|approx\.?|worth|amount|:)?\s*(?:₹|rs\.?)?\s*(?=\d)",
                          r"(?:loan|borrow|need|want|require|chahiye|चाहिए|लोन|amount)"])
    if v is not None and v not in (out.get("monthly_income"), out.get("existing_emi"), out.get("co_applicant_income")):
        out["loan_amount"] = v
    elif "loan_amount" not in out:
        # Fallback: the largest money figure that isn't already claimed
        claimed = {out.get(k) for k in ("monthly_income", "existing_emi", "co_applicant_income", "property_value", "vehicle_price")}
        amounts = [parse_money(mm.group(1), mm.group(2)) for mm in MONEY.finditer(work)]
        amounts = [a for a in amounts if a >= 10000 and a not in claimed]
        if amounts:
            out["loan_amount"] = max(amounts)

    # Education loans are underwritten on the co-applicant (parent/guardian): a student rarely has
    # their own income/score, so income, score and EMI figures are mapped to the co-applicant.
    if lt == "education":
        for src, dst in (("monthly_income", "co_applicant_income"), ("credit_score", "co_applicant_credit_score"), ("existing_emi", "co_applicant_existing_emi")):
            if src in out and dst not in out:
                out[dst] = out.pop(src)
        out.pop("employment_type", None)

    # Plausibility guards
    if out.get("monthly_income") and out["monthly_income"] < 1000:
        del out["monthly_income"]
    if out.get("loan_amount") and out["loan_amount"] < 10000:
        del out["loan_amount"]
    return out


def detect_employment(tl: str) -> Optional[str]:
    if re.search(r"self[- ]?employed|business|businessman|freelanc|shop|own (?:a|my) |proprietor|vyapar|व्यापार|dukaan|consultant|doctor|ca\b|lawyer|entrepreneur", tl):
        return "self_employed"
    if re.search(r"salaried|salary|employee|job|naukri|नौकरी|सैलरी|सेलरी|वेतन|तनख्वाह|take[- ]?home|work(?:ing)? (?:at|in|for|with)|software|engineer|teacher|manager|government|private company|mnc|tcs|infosys", tl):
        return "salaried"
    return None
