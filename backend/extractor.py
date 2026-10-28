"""Rule-based extraction of applicant facts from free text (English / Hindi / Hinglish).

Powers the deterministic agent (no LLM, or LLM unavailable) and serves as the
eval baseline. Approach:

1. Normalise (NFC, Devanagari digits) and split the message into clauses.
2. Find every figure (numbers.figures) and score it against field keywords in
   the same clause; nearer keywords win, keywords before the figure weigh more.
3. Assign figures to fields greedily (one figure -> one field), applying per-field
   validity (a credit score is 300-900, an age has no money unit, ...).
4. Owner of income / score / EMI (applicant vs. spouse / parent) comes from the
   clause; education loans are underwritten on the co-applicant.
5. Loan type changes only on an explicit request, never on a passing mention
   ("I pay EMI on my home loan").
"""
from __future__ import annotations

import re
from typing import Any, Optional

from .numbers import Figure, figures, normalize_text

# ------------------------------------------------------------------ vocab
CO_OWNER = r"\b(?:father|mother|parent|parents|papa|mummy|dad|mom|guardian|wife|husband|spouse|co[- ]?applicant|he|she|his|her|uncle|brother|sister)\b|पिता|माता|पति|पत्नी|उनका|उनकी|उनके"
SELF_OWNER = r"\b(?:i|i'm|im|my|me|mera|meri|mere|main|mujhe)\b|मेरी|मेरा|मेरे|मैं|मुझे"

FIELD_KEYWORDS: dict[str, str] = {
    "income": r"\b(?:salary|salaried|income|earn\w*|take[- ]?home|kamat\w*|kamaa\w*|make|makes|making|pay ?check|in[- ]hand|per month|pm|p\.m\.|monthly|a month|mahina|mahine)\b"
              r"|कमा\w*|आय|वेतन|सैलरी|सेलरी|तनख्वाह|प्रति माह",
    "emi": r"\b(?:emis?|installments?|instalments?|paying|pays?|bharta|bharti|bharte)\b|ईएमआई|किस्त",
    "score": r"\b(?:cibil|credit score|score|experian|crif)\b|सिबिल|क्रेडिट स्कोर|स्कोर",
    "age": r"\b(?:age|aged|umar|umr)\b|उम्र|आयु",
    "loan": r"\b(?:loan|borrow|need|want|require|looking for|amount|chahiye|lena|leni|finance|meant|make it|instead|actually)\b|चाहिए|लोन",
    "property": r"\b(?:property|flat|house|home|apartment|plot|villa|ghar|makaan)\b(?!\s*loan)[^,.;]{0,15}?\b(?:worth|value|valued|costs?|costing|price|priced|keemat|kimat|ka|ki|of)\b"
                r"|\b(?:property|flat|apartment|plot|villa)\b(?!\s*loan)|\b(?:worth|valued at|costing|keemat|kimat)\b|कीमत|मूल्य",
    "vehicle": r"\b(?:on[- ]road|ex[- ]showroom)\b|\b(?:car|vehicle|bike|scooter|gaadi|gadi|suv)\b[^,.;]{0,15}?\b(?:worth|value|costs?|costing|price|priced|keemat|kimat|ka|ki)\b"
               r"|गाड़ी[^,.;]{0,10}कीमत|\b(?:worth|costing|keemat|kimat)\b|कीमत",
}
EXCLUDE_MONEY = r"\b(?:fd|fixed deposit|deposit|savings?|saving|bank balance|invest\w*|ctc|package|bonus|insurance|policy|gold)\b"
ANNUAL = r"\blpa\b|per annum|\bp\.?a\.?\b|a year|per year|yearly|annual\w*|saalana|सालाना|वार्षिक"
YEARS_UNIT = re.compile(r"^\s*-?\s*(?:(?:years?|yrs?|yr|yo|saal|sal)(?![a-z])|y/o|साल|varsh|वर्ष)", re.I)
MONTHS_UNIT = re.compile(r"^\s*-?\s*(?:(?:months?|mos?|mahine|mahina)(?![a-z])|महीने|महीना)", re.I)
AGE_AFTER_YEARS = re.compile(r"^\s*-?\s*(?:years?|yrs?|saal|साल)\s*(?:old|ka|ki|का|की)\b|^\s*(?:y/o|yo)\b", re.I)
EXPERIENCE = re.compile(r"\b(?:experience|exp|working|worked|work|job|joined|service|naukri|kaam)\b|नौकरी", re.I)
AGO = re.compile(r"^\s*-?\s*(?:years?|yrs?|months?|saal|mahine)\s*(?:ago|pehle|back)\b|^\s*(?:years?|months?)\s+of\s+(?:experience|exp|work)", re.I)
SELF_AGE = re.compile(r"(?:\b(?:i am|i'm|im|main|me)\s*|मैं\s*)$", re.I)
NEGATED = re.compile(r"\b(?:not|nahi|nahin)\s*(?:₹|rs\.?)?\s*$", re.I)
# "." and "," split clauses except inside numbers ("9.6", "60,000")
CLAUSE_SPLIT = re.compile(r"(?<!\d)[.,]|[.,](?!\d)|[;!?।\n]|\s(?:and|but|aur|lekin|while|whereas)\s", re.I)

ZERO_EMI = re.compile(
    r"(?:\b(?:no|not|don'?t|do not|dont|never|without|zero|nil|koi|bina)\b|नहीं|कोई|बिना)[^.;।]{0,30}?(?:\bemis?\b|\bloans?\b|\bobligations?\b|\bdues\b|ईएमआई|लोन|कर्ज)"
    r"|(?:\bemis?\b|\bloans?\b|ईएमआई|लोन)[^.;।]{0,15}?(?:\b(?:nil|zero|none|nahi|nahin|no)\b|नहीं)", re.I)

LOAN_WORDS = {
    "personal": r"personal|पर्सनल|व्यक्तिगत",
    "home": r"home|housing|house|ghar|होम|घर|मकान",
    "auto": r"car|auto|vehicle|bike|two[- ]wheeler|gaadi|gadi|गाड़ी|कार",
    "education": r"education|educational|study|student|एजुकेशन|शिक्षा",
}
LOAN_MENTION = re.compile(r"(?P<w>" + "|".join(f"(?:{v})" for v in LOAN_WORDS.values()) + r")\s*(?:loan|लोन)", re.I)
OBLIGATION = re.compile(r"\b(?:emis?|pay|pays|paying|paid|existing|running|already|ongoing|outstanding|bharta|bharti|bharte|chal raha|has an?|have an?)\b|ईएमआई", re.I)
REQUEST = re.compile(r"\b(?:want|need|looking|apply|applying|require|chahiye|lena|leni|instead|actually|switch|change|take|get|interested|for a)\b|चाहिए|लेना", re.I)
NEGATION_BEFORE = re.compile(r"\b(?:no|not|don'?t|without|koi nahi)\s+(?:\w+\s+)?$", re.I)
INTENT = {
    "auto": re.compile(r"\b(?:buy|buying|purchase|kharid\w*)\b[^.;,]{0,25}\b(?:car|bike|vehicle|scooter|gaadi|suv)\b|खरीद[^.;,]{0,15}(?:गाड़ी|कार)", re.I),
    "home": re.compile(r"\b(?:buy|buying|purchase|kharid\w*|new|naya)\b[^.;,]{0,20}\b(?:home|house|flat|apartment|ghar|makaan)\b", re.I),
    "education": re.compile(r"\b(?:study|studies|padhai|ms|mba|masters|college|university|admission|course fee|course in|course at)\b|पढ़ाई", re.I),
}

EMPLOYMENT_PATTERNS = [
    ("salaried", re.compile(r"\bsalaried\b|नौकरीपेशा", re.I)),
    ("self_employed", re.compile(r"\bself[- ]?employed\b|स्वरोज़गार|स्वरोजगार", re.I)),
    ("not_employed", re.compile(r"\b(?:unemployed|not working|no job|jobless|lost my job|retired|pension\w*|homemaker|housewife)\b|बेरोज़गार", re.I)),
    ("self_employed", re.compile(r"\b(?:businessman|business owner|shopkeeper|freelanc\w*|proprietor|entrepreneur|trader|vyapar\w*|dukaan\w*|karobar)\b"
                                 r"|\b(?:my|own|run|runs|running|have|do|in)\s+(?:a\s+|my\s+|own\s+)?(?:\w+\s+)?(?:business|shop|firm|clinic|practice|dukaan|store)\b"
                                 r"|\bbusiness\s+kart\w*|\bconsultant\b(?!\s+(?:at|in|with|for))|\bca\b|व्यापार|दुकान", re.I)),
    ("salaried", re.compile(r"\b(?:employee|job|naukri|engineer|developer|teacher|manager|analyst|officer|nurse|clerk)\b"
                            r"|\b(?:work|working|consultant|employed)\s+(?:at|in|for|with|as)\b|\b(?:mnc|govt|government|private company)\b"
                            r"|\bsalary\b|नौकरी|सैलरी|सेलरी|वेतन|तनख्वाह", re.I)),
]

ABROAD = re.compile(r"\b(?:abroad|overseas|foreign|outside india|usa|u\.s\.?|the us|america|uk|united kingdom|england|london|canada|"
                    r"australia|germany|ireland|france|europe|singapore|new zealand|japan|dubai|uae|videsh)\b|विदेश", re.I)
INDIA = re.compile(r"\b(?:india|indian|bharat|domestic|iit|iim|nit|delhi|mumbai|bangalore|bengaluru|pune|chennai|hyderabad|kolkata|"
                   r"ahmedabad|noida|gurgaon|jaipur|lucknow)\b|भारत", re.I)
NOT_ABROAD = re.compile(r"\bnot\s+(?:abroad|overseas|outside)\b", re.I)
YES = re.compile(r"^\s*(?:yes|yeah|yep|haan|ha|ji|sure|correct|right)\b|^\s*हाँ|^\s*हां", re.I)
NO = re.compile(r"^\s*(?:no|nope|nahi|nahin|none|nil|zero)\b|^\s*नहीं", re.I)

FIELD_OF = {  # internal key -> profile field (applicant); co-applicant variants handled separately
    "income": "monthly_income", "emi": "existing_emi", "score": "credit_score", "age": "age",
    "loan": "loan_amount", "property": "property_value", "vehicle": "vehicle_price",
    "tenure": "tenure_years", "experience": "employment_months",
}
CO_FIELD = {"income": "co_applicant_income", "emi": "co_applicant_existing_emi", "score": "co_applicant_credit_score"}


# ------------------------------------------------------------------ helpers
def _clauses(text: str) -> list[tuple[int, int]]:
    spans, start = [], 0
    for m in CLAUSE_SPLIT.finditer(text):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(text)))
    return spans


def _clause_of(pos: int, spans: list[tuple[int, int]]) -> tuple[int, int]:
    for a, b in spans:
        if a <= pos < b or (pos == b and a < b):
            return a, b
    return 0, 0


def _nearest(pattern: str, text: str, a: int, b: int, f: Figure) -> Optional[float]:
    """Distance from figure to the nearest keyword in the clause (keywords after count 1.5x)."""
    best = None
    for m in re.finditer(pattern, text[a:b], re.I):
        ks, ke = a + m.start(), a + m.end()
        if ke <= f.start:
            d = f.start - ke
        elif ks >= f.end:
            d = (ks - f.end) * 1.5
        else:
            continue
        best = d if best is None else min(best, d)
    return best


def _owner(text: str, a: int, f: Figure) -> str:
    left = text[a:f.start]
    co = [m.end() for m in re.finditer(CO_OWNER, left, re.I)]
    me = [m.end() for m in re.finditer(SELF_OWNER, left, re.I)]
    if co and (not me or max(co) > max(me)):
        return "co"
    return "self"


def detect_employment(text: str) -> Optional[str]:
    for value, pat in EMPLOYMENT_PATTERNS:
        if pat.search(text):
            return value
    return None


def detect_loan_type(text: str, context: Optional[str] = None, asked: bool = False) -> Optional[str]:
    """Loan type the user is *asking for*. Passing mentions of existing loans don't count."""
    tl = normalize_text(text).lower()
    for a, b in _clauses(tl):
        clause = tl[a:b]
        for m in LOAN_MENTION.finditer(clause):
            word = m.group("w")
            if NEGATION_BEFORE.search(clause[:m.start()]) or OBLIGATION.search(clause):
                continue
            if context and not asked and not REQUEST.search(clause):
                continue
            for lt, pat in LOAN_WORDS.items():
                if re.fullmatch(pat, word, re.I):
                    return lt
    if context and not asked:
        return None
    for lt, pat in INTENT.items():
        if pat.search(tl):
            return lt
    if asked:
        for lt, pat in LOAN_WORDS.items():
            if re.search(pat, tl, re.I):
                return lt
    return None


def _study_abroad(text: str, direct: bool) -> Optional[bool]:
    if NOT_ABROAD.search(text) or INDIA.search(text):
        return False
    if ABROAD.search(text):
        return True
    if direct:
        if YES.search(text):
            return True
        if NO.search(text):
            return False
        return False  # answered with a place we don't recognise as foreign -> India
    return None


def _valid(field: str, f: Figure, years_unit: bool, months_unit: bool) -> bool:
    v = f.value
    money = f.unit is not None or f.currency
    if field == "age":
        return not money and not months_unit and 15 <= v <= 90 and v == int(v)
    if field == "score":
        return not money and not years_unit and 300 <= v <= 900
    if field in ("tenure", "experience"):
        return (years_unit or months_unit) and not money
    if years_unit or months_unit:
        return False
    if field == "emi":
        return v >= 100 or v == 0
    if field == "income":
        return v >= 1000
    return v >= 10000  # loan / property / vehicle


# ------------------------------------------------------------------ main entry
def extract(text: str, expected_field: Optional[str] = None, loan_type: Optional[str] = None) -> dict[str, Any]:
    """Pull applicant facts from `text`. `expected_field` is the slot the bot just asked for."""
    t = normalize_text(text)
    tl = t.lower()
    out: dict[str, Any] = {}
    spans = _clauses(tl)

    # --- categorical facts
    lt = detect_loan_type(tl, context=loan_type, asked=expected_field == "loan_type")
    if lt:
        out["loan_type"] = lt
    eff_type = lt or loan_type

    emp = detect_employment(tl)
    if emp and (emp != "not_employed" or expected_field == "employment_type" or re.search(r"\bi\b|\bmain\b|मैं", tl)):
        out["employment_type"] = emp
    if eff_type == "education" or expected_field == "study_abroad":
        sa = _study_abroad(tl, direct=expected_field == "study_abroad")
        if sa is not None:
            out["study_abroad"] = sa
    elif ABROAD.search(tl) and INTENT["education"].search(tl):
        out["study_abroad"] = True

    # --- figures -> candidate fields
    figs = [f for f in figures(tl) if not NEGATED.search(tl[:f.start])]
    candidates: list[tuple[float, int, str]] = []
    for i, f in enumerate(figs):
        a, b = _clause_of(f.start, spans)
        right = tl[f.end:b]
        is_money = f.unit is not None or f.currency  # "70 hazaar mahine" is money per month, not a duration
        years_unit = not is_money and bool(YEARS_UNIT.match(right))
        months_unit = not is_money and bool(MONTHS_UNIT.match(right))
        clause = tl[a:b]
        excluded = bool(re.search(EXCLUDE_MONEY, clause))

        if years_unit or months_unit:
            if AGE_AFTER_YEARS.match(right) and years_unit:
                candidates.append((0, i, "age"))
            elif AGO.match(right) or EXPERIENCE.search(tl[max(a, f.start - 25):f.start]) or re.match(r"^\s*\w+\s+of\s+(?:experience|exp)", right):
                candidates.append((0, i, "experience"))
            else:
                candidates.append((1, i, "tenure"))
            continue
        if SELF_AGE.search(tl[max(a, f.start - 8):f.start]) and _valid("age", f, False, False):
            candidates.append((0, i, "age"))
        for key, pat in FIELD_KEYWORDS.items():
            if excluded and key in ("loan", "property", "vehicle", "income"):
                continue
            if key == "property" and eff_type not in (None, "home"):
                continue
            if key == "vehicle" and eff_type not in (None, "auto"):
                continue
            d = _nearest(pat, tl, a, b, f)
            if d is not None and _valid(key, f, False, False):
                candidates.append((d + 2, i, key))
        if not excluded and f.unit in ("lakh", "lakhs", "lac", "lacs", "laakh", "लाख", "l", "crore", "crores", "cr", "karod", "करोड़") \
                and expected_field in (None, "loan_amount") and _valid("loan", f, False, False):
            candidates.append((60, i, "loan"))  # weak fallback: a lakh/crore figure with no keyword is the loan amount

    # --- greedy assignment: one figure -> one field, one field -> one figure
    used_figs: set[int] = set()
    assigned: dict[str, tuple[int, Figure]] = {}
    for _, i, key in sorted(candidates):
        f = figs[i]
        a, _ = _clause_of(f.start, spans)
        target = key
        if key in CO_FIELD and (_owner(tl, a, f) == "co" or eff_type == "education"):
            target = "co_" + key
        if i in used_figs or target in assigned:
            continue
        used_figs.add(i)
        assigned[target] = (i, f)

    for target, (i, f) in assigned.items():
        a, b = _clause_of(f.start, spans)
        right = tl[f.end:b]
        if target in ("tenure", "experience"):
            months = bool(MONTHS_UNIT.match(right))
            val = f.value / 12 if months else f.value
            extra = re.match(r"^\s*(?:years?|yrs?|saal|साल)\s*(?:and\s*)?(\d+)\s*(?:months?|mahine)", right, re.I)
            if extra and not months:
                val += int(extra.group(1)) / 12
                for j, g in enumerate(figs):
                    if g.start == f.end + extra.start(1):
                        used_figs.add(j)
            if target == "tenure" and 0.25 <= val <= 40:
                out["tenure_years"] = round(val, 4)
            elif target == "experience":
                out["employment_months"] = round(val * 12)
            continue
        base = target[3:] if target.startswith("co_") else target
        val = f.value
        if base == "income" and (f.annual or re.search(ANNUAL, tl[a:b])):
            val = val / 12
        field_name = CO_FIELD[base] if target.startswith("co_") else FIELD_OF[base]
        out[field_name] = float(val)

    # --- zero EMI from negations, unless an explicit EMI figure was given
    emi_key = "co_applicant_existing_emi" if eff_type == "education" else "existing_emi"
    if emi_key not in out and "existing_emi" not in out and ZERO_EMI.search(tl):
        leftover_answer = expected_field in ("existing_emi", "co_applicant_existing_emi") and any(
            i not in used_figs and _valid("emi", f, False, False) for i, f in enumerate(figs))
        if not leftover_answer:
            out[emi_key] = 0.0

    # --- direct answer to the question just asked (a bare figure, or yes/no)
    if expected_field and expected_field not in out:
        free = [(i, f) for i, f in enumerate(figs) if i not in used_figs]
        if expected_field in ("existing_emi", "co_applicant_existing_emi") and not free and NO.search(tl):
            out[expected_field] = 0.0
        elif len(free) == 1:
            _, f = free[0]
            right = tl[f.end:]
            years_unit, months_unit = bool(YEARS_UNIT.match(right)), bool(MONTHS_UNIT.match(right))
            key = {"monthly_income": "income", "co_applicant_income": "income", "existing_emi": "emi",
                   "co_applicant_existing_emi": "emi", "credit_score": "score", "co_applicant_credit_score": "score",
                   "age": "age", "loan_amount": "loan", "property_value": "property", "vehicle_price": "vehicle",
                   "tenure_years": "tenure"}.get(expected_field)
            if key == "tenure":
                if not (f.unit or f.currency):
                    val = f.value / 12 if months_unit else f.value
                    extra = re.match(r"^\s*(?:years?|yrs?|saal|साल)\s*(?:and\s*)?(\d+)\s*(?:months?|mahine)", right, re.I)
                    if extra:
                        val += int(extra.group(1)) / 12
                    if 0.25 <= val <= 40:
                        out[expected_field] = round(val, 4)
            elif key and _valid(key, f, years_unit, months_unit):
                val = f.value / 12 if key == "income" and (f.annual or re.search(ANNUAL, tl)) else f.value
                out[expected_field] = float(val)

    # --- education loans are underwritten on the co-applicant
    if eff_type == "education":
        for src, dst in (("monthly_income", "co_applicant_income"), ("credit_score", "co_applicant_credit_score"),
                         ("existing_emi", "co_applicant_existing_emi")):
            if src in out and dst not in out:
                out[dst] = out.pop(src)
            else:
                out.pop(src, None)
        out.pop("employment_type", None)
        out.pop("employment_months", None)
    return out
