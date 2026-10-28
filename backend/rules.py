"""Deterministic loan eligibility rules engine.

This is the *decision* half of the hybrid design: every eligibility verdict comes
from these auditable rules (loaded from data/rules.json), never from the LLM.
The LLM only extracts applicant facts and explains the result.

Design guarantees (checked by tests/fuzz_rules.py):
- Input is validated: non-finite, negative or out-of-range values are rejected
  (reported in `invalid_fields`) instead of crashing or skewing the verdict.
- Every amount shown as "you qualify for up to X" re-evaluates as eligible at X.
- Every improvement suggestion is only shown when applying it actually helps.
- Displayed caps are rounded down and required amounts rounded up, never the
  other way around.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from .numbers import normalize_text, parse_number

RULES_PATH = Path(__file__).resolve().parent.parent / "data" / "rules.json"

LOAN_TYPES = ("personal", "home", "auto", "education")
EMPLOYMENT_TYPES = ("salaried", "self_employed", "not_employed")
CREDIT_UNKNOWN = "unknown"
EPS = 1e-9

# Fields the engine needs before it can give a verdict, per product.
REQUIRED_FIELDS: dict[str, list[str]] = {
    "personal": ["loan_amount", "tenure_years", "age", "monthly_income", "employment_type", "credit_score", "existing_emi"],
    "home": ["loan_amount", "tenure_years", "age", "monthly_income", "employment_type", "credit_score", "existing_emi", "property_value"],
    "auto": ["loan_amount", "tenure_years", "age", "monthly_income", "employment_type", "credit_score", "existing_emi", "vehicle_price"],
    "education": ["loan_amount", "tenure_years", "age", "study_abroad", "co_applicant_income", "co_applicant_credit_score", "co_applicant_existing_emi"],
}
# Fields that only make sense for one product; dropped when the applicant switches product.
PRODUCT_SPECIFIC = {
    "home": {"property_value"},
    "auto": {"vehicle_price"},
    "education": {"study_abroad", "co_applicant_income", "co_applicant_credit_score", "co_applicant_existing_emi"},
}

FIELD_LABELS = {
    "loan_type": "type of loan",
    "loan_amount": "loan amount",
    "tenure_years": "repayment tenure (years)",
    "age": "age",
    "monthly_income": "net monthly income",
    "employment_type": "employment type (salaried / self-employed)",
    "credit_score": "credit score",
    "existing_emi": "existing monthly EMIs",
    "property_value": "property value",
    "vehicle_price": "vehicle on-road price",
    "study_abroad": "whether the course is in India or abroad",
    "co_applicant_income": "co-applicant's net monthly income",
    "co_applicant_credit_score": "co-applicant's credit score",
    "co_applicant_existing_emi": "co-applicant's existing monthly EMIs",
    "employment_months": "total work experience (months)",
}

# Valid ranges (inclusive). Values outside are rejected as invalid, not clamped.
NUMERIC_RANGES: dict[str, tuple[float, float]] = {
    "loan_amount": (1_000, 1e10),
    "tenure_years": (0.25, 40),
    "age": (15, 100),
    "monthly_income": (0, 1e9),
    "existing_emi": (0, 1e9),
    "credit_score": (300, 900),
    "property_value": (10_000, 1e11),
    "vehicle_price": (10_000, 1e9),
    "co_applicant_income": (0, 1e9),
    "co_applicant_credit_score": (300, 900),
    "co_applicant_existing_emi": (0, 1e9),
    "employment_months": (0, 720),
}
ALLOWED_FIELDS = set(NUMERIC_RANGES) | {"loan_type", "employment_type", "study_abroad"}


def load_rules() -> dict[str, Any]:
    with open(RULES_PATH, encoding="utf-8") as f:
        return json.load(f)


RULES = load_rules()


# ---------------------------------------------------------------- formatting
def fmt_inr(amount: float | None, rounding: str = "nearest") -> str:
    """Indian style: ₹12.5 L / ₹1.2 Cr. rounding='floor' for caps, 'ceil' for amounts the user must find."""
    if amount is None or not math.isfinite(float(amount)):
        return "—"
    amount = float(amount)
    rnd = {"floor": math.floor, "ceil": math.ceil}.get(rounding, round)

    def two_dp(x: float) -> str:
        v = rnd(x * 100 + (EPS if rounding == "floor" else -EPS if rounding == "ceil" else 0)) / 100
        return f"{v:.2f}".rstrip("0").rstrip(".")

    if amount >= 1e7:
        return f"₹{two_dp(amount / 1e7)} Cr"
    if amount >= 1e5:
        return f"₹{two_dp(amount / 1e5)} L"
    return f"₹{int(rnd(amount)):,}"


def fmt_pct(ratio: float, limit: float) -> str:
    """Whole percent normally; one decimal near the limit so '50% vs 50%' can't hide a fail."""
    if not math.isfinite(ratio):
        return "n/a"
    if abs(ratio - limit) >= 0.01:
        return f"{ratio:.0%}"
    if ratio > limit + EPS and round(ratio * 1000) <= round(limit * 1000):
        return f"just above {limit:.0%}"
    return f"{ratio:.1%}"


def ceil_to(x: float, step: float) -> float:
    return math.ceil(x / step - EPS) * step


def floor_to(x: float, step: float) -> float:
    return math.floor(x / step + EPS) * step


# ---------------------------------------------------------------- maths
def emi(principal: float, annual_rate_pct: float, tenure_years: float) -> float:
    n = max(int(round(tenure_years * 12)), 1)
    r = annual_rate_pct / 1200.0
    if r == 0:
        return principal / n
    return principal * r * (1 + r) ** n / ((1 + r) ** n - 1)


def max_principal_for_emi(target_emi: float, annual_rate_pct: float, tenure_years: float) -> float:
    """Inverse of emi(): the largest principal whose EMI is <= target_emi."""
    if target_emi <= 0:
        return 0.0
    n = max(int(round(tenure_years * 12)), 1)
    r = annual_rate_pct / 1200.0
    if r == 0:
        return target_emi * n
    return target_emi * ((1 + r) ** n - 1) / (r * (1 + r) ** n)


def credit_band(score: float | None) -> str:
    if not isinstance(score, (int, float)):
        return "Unknown"
    for band in RULES["credit_score_bands"]:
        if score >= band["min"]:
            return band["label"]
    return "Poor"


def ltv_ratio_for(product: dict, amount: float) -> float:
    """Max LTV that applies to a loan of this size."""
    for slab in product.get("ltv_slabs", []):
        if slab["upto"] is None or amount <= slab["upto"]:
            return slab["max_ltv"]
    return product.get("max_ltv", 1.0)


def max_loan_by_ltv(product: dict, asset_value: float) -> float:
    """Largest loan the asset supports across all LTV slabs (not just the slab of the requested amount)."""
    if "ltv_slabs" not in product:
        return asset_value * product.get("max_ltv", 1.0)
    best = 0.0
    for slab in product["ltv_slabs"]:
        cap = asset_value * slab["max_ltv"]
        best = max(best, cap if slab["upto"] is None else min(slab["upto"], cap))
    return best


# ---------------------------------------------------------------- result types
@dataclass
class Check:
    rule: str
    passed: bool
    detail: str
    hard: bool = True  # hard = blocks eligibility; soft = warning only

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Evaluation:
    status: str  # ELIGIBLE | CONDITIONAL | NOT_ELIGIBLE | INCOMPLETE
    loan_type: str
    checks: list[Check] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    invalid_fields: list[str] = field(default_factory=list)
    emi: Optional[float] = None
    foir: Optional[float] = None
    interest_rate: Optional[float] = None
    max_eligible_amount: Optional[float] = None
    requested_amount: Optional[float] = None
    tenure_years: Optional[float] = None
    improvements: list[str] = field(default_factory=list)
    summary: str = ""
    score: int = 0  # 0-100 eligibility strength, for the UI gauge

    def as_dict(self) -> dict:
        d = asdict(self)
        d["checks"] = [c.as_dict() for c in self.checks]
        d["missing_field_labels"] = [FIELD_LABELS.get(f, f) for f in self.missing_fields]
        d["emi_display"] = fmt_inr(self.emi) if self.emi else None
        d["max_eligible_display"] = fmt_inr(self.max_eligible_amount, "floor") if self.max_eligible_amount else None
        d["requested_display"] = fmt_inr(self.requested_amount) if self.requested_amount else None
        return d


# ---------------------------------------------------------------- normalisation & validation
LOAN_ALIASES = {
    "personal": "personal", "pl": "personal",
    "home": "home", "housing": "home", "house": "home", "mortgage": "home", "flat": "home",
    "auto": "auto", "car": "auto", "vehicle": "auto", "two wheeler": "auto", "two-wheeler": "auto", "bike": "auto",
    "motorcycle": "auto", "scooter": "auto",
    "education": "education", "educational": "education", "study": "education", "student": "education",
}
SALARIED = {"salaried", "salary", "employee", "employed", "job", "service", "government", "govt", "private job",
            "salaried employee", "working professional", "naukri"}
SELF_EMPLOYED = {"self_employed", "self employed", "self-employed", "business", "businessman", "business owner",
                 "freelancer", "freelance", "professional", "self", "self employed professional", "consultant",
                 "proprietor", "entrepreneur", "shop owner", "doctor", "ca", "lawyer", "trader"}
NOT_EMPLOYED = {"not_employed", "unemployed", "not employed", "not working", "student", "retired", "homemaker",
                "housewife", "none", "no job", "jobless"}


def _norm_employment(val: Any) -> Optional[str]:
    v = re.sub(r"[\s_]+", " ", str(val).strip().lower())
    if v.replace(" ", "_") in EMPLOYMENT_TYPES:
        return v.replace(" ", "_")
    if v in NOT_EMPLOYED:
        return "not_employed"
    if v in SELF_EMPLOYED or v.startswith("self employed") or v.startswith("self-employed"):
        return "self_employed"
    if v in SALARIED:
        return "salaried"
    return None


def _norm_loan_type(val: Any) -> Optional[str]:
    v = re.sub(r"\s+", " ", str(val).strip().lower())
    v = re.sub(r"\s*loan$", "", v)
    return LOAN_ALIASES.get(v)


def _norm_study_abroad(val: Any) -> Optional[bool]:
    if isinstance(val, bool):
        return val
    s = normalize_text(str(val)).strip().lower()
    if re.search(r"\bnot\s+(?:abroad|overseas|outside)", s):
        return False
    if re.search(r"\b(india|indian|bharat|domestic)\b|भारत", s):
        return False
    if re.search(r"\b(abroad|overseas|foreign|outside|usa|us|uk|canada|australia|germany|ireland|france|europe|"
                 r"singapore|new zealand|japan|dubai|uae|videsh)\b|विदेश", s):
        return True
    if s in ("true", "yes", "y", "1"):
        return True
    if s in ("false", "no", "n", "0"):
        return False
    return None


def validate_profile(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Coerce loosely-typed applicant data (API, LLM tool calls, extractor) into engine input.

    Returns (clean_profile, invalid_fields). Unknown keys are ignored. Invalid values are
    dropped and reported so the conversation can ask for them again.
    """
    out: dict[str, Any] = {}
    invalid: list[str] = []
    for key, val in (raw or {}).items():
        if key not in ALLOWED_FIELDS or val is None or val == "":
            continue
        if key == "loan_type":
            v = _norm_loan_type(val)
        elif key == "employment_type":
            v = _norm_employment(val)
        elif key == "study_abroad":
            v = _norm_study_abroad(val)
        elif key in ("credit_score", "co_applicant_credit_score") and isinstance(val, str) and val.strip().lower() == CREDIT_UNKNOWN:
            v = CREDIT_UNKNOWN
        else:
            v = parse_number(val)
            lo, hi = NUMERIC_RANGES[key]
            if v is not None and not (lo <= v <= hi):
                v = None
        if v is None:
            invalid.append(key)
        else:
            out[key] = v
    return out, invalid


def normalize_profile(raw: dict[str, Any]) -> dict[str, Any]:
    return validate_profile(raw)[0]


parse_amount = parse_number  # public name kept for integrations

LOAN_LABEL = {
    "personal": {"hi": "पर्सनल लोन", "hinglish": "personal loan"},
    "home": {"hi": "होम लोन", "hinglish": "home loan"},
    "auto": {"hi": "कार लोन", "hinglish": "car loan"},
    "education": {"hi": "एजुकेशन लोन", "hinglish": "education loan"},
}
# Verdict summaries per language. Rule details stay in English and are passed through as {details}.
SUMMARY_T = {
    "en": {
        "eligible": "You are eligible for a {label} of {amount} over {tenure} years. Indicative EMI: {emi}/month at {rate}% p.a.",
        "cond_min": "The minimum {label} is {min_amt}; you are eligible for anything from {min_amt} up to {max_amt} over {tenure} years.",
        "cond_cap": "{amount} is above what you qualify for, but you are eligible for up to {max_amt} over {tenure} years (EMI about {emi_max}/month).",
        "cond_soft": "You are eligible for {amount} over {tenure} years, subject to: {details}",
        "not_el": "You are not eligible for a {label} of {amount} right now. Main reasons: {details}",
    },
    "hi": {
        "eligible": "आप {tenure} साल के लिए {amount} के {label} के पात्र हैं। सांकेतिक EMI: {emi}/माह, ब्याज दर {rate}% वार्षिक।",
        "cond_min": "न्यूनतम {label} {min_amt} है; आप {tenure} साल के लिए {min_amt} से {max_amt} तक के लिए पात्र हैं।",
        "cond_cap": "{amount} आपकी पात्रता से ज़्यादा है, लेकिन आप {tenure} साल के लिए {max_amt} तक के लिए पात्र हैं (लगभग {emi_max}/माह की EMI पर)।",
        "cond_soft": "आप {tenure} साल के लिए {amount} के पात्र हैं, इन शर्तों के साथ: {details}",
        "not_el": "आप अभी {amount} के {label} के लिए पात्र नहीं हैं। मुख्य कारण: {details}",
    },
    "hinglish": {
        "eligible": "Aap {tenure} saal ke liye {amount} ke {label} ke liye eligible hain. Indicative EMI: {emi}/month at {rate}% p.a.",
        "cond_min": "Minimum {label} {min_amt} hai; aap {tenure} saal ke liye {min_amt} se {max_amt} tak ke liye eligible hain.",
        "cond_cap": "{amount} aapki eligibility se zyada hai, lekin aap {tenure} saal ke liye {max_amt} tak ke liye eligible hain (lagbhag {emi_max}/month ki EMI par).",
        "cond_soft": "Aap {tenure} saal ke liye {amount} ke liye eligible hain, in sharton ke saath: {details}",
        "not_el": "Aap abhi {amount} ke {label} ke liye eligible nahi hain. Main reasons: {details}",
    },
}


# ---------------------------------------------------------------- the engine
def evaluate(profile_in: dict[str, Any], lang: str = "en") -> Evaluation:
    p, invalid = validate_profile(profile_in)
    loan_type = p.get("loan_type")
    if loan_type not in LOAN_TYPES:
        return Evaluation(status="INCOMPLETE", loan_type="", missing_fields=["loan_type"], invalid_fields=invalid,
                          summary="I need to know which loan you are looking for: personal, home, car or education.")

    missing = [f for f in REQUIRED_FIELDS[loan_type] if p.get(f) is None]
    if missing:
        return Evaluation(status="INCOMPLETE", loan_type=loan_type, missing_fields=missing, invalid_fields=invalid,
                          summary="A few more details are needed before I can check eligibility.")

    product = RULES["products"][loan_type]
    common = RULES["common"]
    checks: list[Check] = []
    advice: list[str] = []  # suggestions for non-capacity failures

    amount = float(p["loan_amount"])
    tenure = float(p["tenure_years"])
    age = float(p["age"])
    rate = product["interest_rate"]

    # --- Who is underwritten
    if loan_type == "education":  # underwritten on the co-applicant (parent/guardian)
        income = float(p["co_applicant_income"])
        score = p["co_applicant_credit_score"]
        existing_emi = float(p["co_applicant_existing_emi"])
        emp_type = "salaried"
        who, score_owner = "Co-applicant", "Co-applicant"
    else:
        income = float(p["monthly_income"])
        score = p["credit_score"]
        existing_emi = float(p["existing_emi"])
        emp_type = p["employment_type"]
        who, score_owner = "Applicant", "Applicant"
        if p.get("co_applicant_income"):  # optional spouse/parent: incomes and obligations clubbed
            income += float(p["co_applicant_income"])
            existing_emi += float(p.get("co_applicant_existing_emi") or 0)
            who = "Combined"
    limits_type = "salaried" if emp_type == "not_employed" else emp_type

    # 1. Tenure within product limits (evaluate at the nearest allowed tenure, flag it)
    lo_t, hi_t = product["min_tenure_years"], product["max_tenure_years"]
    if tenure < lo_t or tenure > hi_t:
        clamped = min(max(tenure, lo_t), hi_t)
        checks.append(Check("tenure_range", False,
                            f"Tenure must be between {lo_t} and {hi_t} years; you asked for {tenure:g}, so I evaluated at {clamped:g} years.",
                            hard=False))
        advice.append(f"Choose a tenure between {lo_t} and {hi_t} years.")
        tenure = clamped
    else:
        checks.append(Check("tenure_range", True, f"Tenure of {tenure:g} years is within the allowed {lo_t}–{hi_t} years."))

    # 2. Employment
    if emp_type == "not_employed":
        checks.append(Check("employment", False, "A regular income source (salaried or self-employed) is required to borrow."))
        advice.append("Apply with an earning family member as the primary applicant, or once you have a regular income.")

    # 3. Age
    max_tenure_for_age = hi_t
    if loan_type == "education":
        lo_a, hi_a = product["student_min_age"], product["student_max_age"]
        ok = lo_a <= age <= hi_a
        checks.append(Check("age", ok, f"Student age {age:g} is {'within' if ok else 'outside'} the {lo_a}–{hi_a} range."))
        if not ok:
            advice.append(f"Education loans are offered to students aged {lo_a}–{hi_a}.")
    else:
        max_at_maturity = common["max_age_at_maturity"][limits_type]
        max_tenure_for_age = min(hi_t, max_at_maturity - age)
        if age < common["min_age"]:
            checks.append(Check("age", False, f"Minimum age is {common['min_age']} (you are {age:g})."))
            advice.append(f"You can apply once you turn {common['min_age']}.")
        elif age + tenure > max_at_maturity + EPS:
            checks.append(Check("age", False,
                                f"Age at loan maturity would be {age + tenure:g}; the limit is {max_at_maturity} for {limits_type.replace('_', '-')} applicants."))
            if max_tenure_for_age >= lo_t:
                advice.append(f"Reduce the tenure to {math.floor(max_tenure_for_age):g} years so the loan closes before age {max_at_maturity}.")
            else:
                advice.append("Consider adding a younger co-applicant as the primary borrower.")
        else:
            checks.append(Check("age", True, f"Age {age:g} with maturity at {age + tenure:g} is within the limit of {max_at_maturity}."))

    # 4. Employment vintage (optional field, only checked when supplied)
    if loan_type != "education" and p.get("employment_months") is not None and emp_type != "not_employed":
        emp_months, min_months = p["employment_months"], common["min_employment_months"][limits_type]
        ok = emp_months >= min_months
        checks.append(Check("employment_vintage", ok, f"{emp_months:g} months of work experience vs. minimum {min_months}."))
        if not ok:
            advice.append(f"Apply after {math.ceil(min_months - emp_months):g} more months of work history.")

    # 5. Minimum income
    min_income = product["min_co_applicant_income"] if loan_type == "education" else product["min_monthly_income"][limits_type]
    ok = income >= min_income
    checks.append(Check("min_income", ok, f"{who} net income {fmt_inr(income)}/month vs. minimum {fmt_inr(min_income)}."))
    if not ok:
        advice.append(f"Minimum income for this product is {fmt_inr(min_income)}/month; an earning co-applicant's income can be added.")

    # 6. Credit score
    min_score = product["min_credit_score"]
    if score == CREDIT_UNKNOWN:
        checks.append(Check("credit_score", False,
                            f"{score_owner} credit score not provided; this product needs at least {min_score}. Check it free on CIBIL before applying.",
                            hard=False))
    else:
        ok = score >= min_score
        checks.append(Check("credit_score", ok, f"{score_owner} credit score {score:g} ({credit_band(score)}) vs. minimum {min_score}."))
        if not ok:
            gap = math.ceil(min_score - score)
            advice.append(f"Improve the credit score by {gap} point{'s' if gap != 1 else ''} (pay EMIs and cards on time, "
                          "keep card utilisation under 30%, avoid new loan enquiries).")
        elif score < min_score + 30:
            checks.append(Check("credit_score_margin", False, "Score is close to the cut-off; a stronger score would get a better rate.", hard=False))

    # 7. Amount within product bounds
    max_amount = (product["max_amount_abroad"] if p.get("study_abroad") else product["max_amount_india"]) \
        if loan_type == "education" else product["max_amount"]
    min_amount = product["min_amount"]
    if amount < min_amount or amount > max_amount:
        checks.append(Check("amount_range", False, f"Amount must be between {fmt_inr(min_amount)} and {fmt_inr(max_amount)} for this product."))
    else:
        checks.append(Check("amount_range", True, f"Requested {fmt_inr(amount)} is within the product range."))

    # 8. Collateral / LTV
    ltv_cap_amount: Optional[float] = None
    asset = p.get("property_value") if loan_type == "home" else p.get("vehicle_price") if loan_type == "auto" else None
    if asset is not None:
        asset = float(asset)
        cap_ratio = ltv_ratio_for(product, amount)
        ltv_cap_amount = max_loan_by_ltv(product, asset)
        ltv = amount / asset
        ok = ltv <= cap_ratio + EPS
        what = "Loan-to-value" if loan_type == "home" else "Financing"
        checks.append(Check("ltv", ok, f"{what} {fmt_pct(ltv, cap_ratio)} of {fmt_inr(asset)} vs. maximum {cap_ratio:.0%} for a loan of this size."))
        if not ok:
            advice.append(f"Increase your down payment by {fmt_inr(ceil_to(amount - ltv_cap_amount, 1000), 'ceil')}, "
                          f"or request up to {fmt_inr(floor_to(ltv_cap_amount, 10000), 'floor')}.")
    elif loan_type == "education" and amount > product["requires_collateral_above"]:
        checks.append(Check("collateral", False,
                            f"Loans above {fmt_inr(product['requires_collateral_above'])} need collateral (property, FD or LIC policy).", hard=False))

    # 9. Repayment capacity: FOIR = (existing EMIs + new EMI) / income
    new_emi = emi(amount, rate, tenure)
    max_foir = product["max_foir"]
    foir = (existing_emi + new_emi) / income if income > 0 else math.inf
    foir_ok = foir <= max_foir + EPS
    income_txt = fmt_inr(income) if income > 0 else "no"
    checks.append(Check("foir", foir_ok,
                        f"Fixed-obligation ratio {fmt_pct(foir, max_foir)} (existing {fmt_inr(existing_emi)} + new EMI {fmt_inr(new_emi)} "
                        f"on {income_txt} income) vs. limit {max_foir:.0%}."))
    if foir_ok and foir > max_foir - 0.05:
        checks.append(Check("foir_margin", False, "Repayment ratio is close to the limit; keep other borrowings low until disbursal.", hard=False))

    # 10. Income multiple cap (unsecured / vehicle products)
    multiple_cap: Optional[float] = None
    if "income_multiple_cap" in product and loan_type != "education":
        multiple_cap = income * product["income_multiple_cap"]
        ok = amount <= multiple_cap + EPS
        times = f"{amount / income:.0f}×" if income > 0 else "—"
        checks.append(Check("income_multiple", ok,
                            f"Requested amount is {times} monthly income vs. cap of {product['income_multiple_cap']}× ({fmt_inr(multiple_cap, 'floor')})."))

    # --- Maximum eligible amount at this tenure (every cap applied)
    def max_for(t: float) -> float:
        headroom = max(income * max_foir - existing_emi, 0.0)
        caps = [max_principal_for_emi(headroom, rate, t), max_amount]
        if multiple_cap is not None:
            caps.append(multiple_cap)
        if ltv_cap_amount is not None:
            caps.append(ltv_cap_amount)
        return floor_to(min(caps), 10000)

    max_eligible = max_for(tenure)

    # --- Verdict
    hard_fails = [c for c in checks if c.hard and not c.passed]
    soft_flags = [c for c in checks if not c.hard and not c.passed]
    capacity_rules = {"foir", "ltv", "income_multiple", "amount_range"}
    only_capacity_fails = bool(hard_fails) and all(c.rule in capacity_rules for c in hard_fails)

    if not hard_fails:
        status = "CONDITIONAL" if soft_flags else "ELIGIBLE"
        max_eligible = max(max_eligible, amount)  # the requested amount itself passed every cap
    elif only_capacity_fails and max_eligible >= min_amount:
        status = "CONDITIONAL"
    else:
        status = "NOT_ELIGIBLE"

    # --- Capacity advice (only what is true and would actually help)
    improvements = list(advice)
    other_fails = [c for c in hard_fails if c.rule != "foir"]
    if only_capacity_fails or (not foir_ok and hard_fails):
        if max_eligible >= min_amount and max_eligible < amount:
            improvements.append(f"Based on your repayment capacity you qualify for up to {fmt_inr(max_eligible, 'floor')} at {tenure:g} years.")
        longest = math.floor(max_tenure_for_age) if loan_type != "education" else hi_t
        if not foir_ok and only_capacity_fails and longest > tenure:
            alt = max_for(longest)
            if alt > max_eligible and alt >= min_amount:
                improvements.append(f"Extending the tenure to {longest:g} years raises your eligibility to about {fmt_inr(alt, 'floor')}.")
        if not foir_ok and income > 0:
            need = (existing_emi + new_emi) - income * max_foir
            if 0 < need <= existing_emi:
                improvements.append(f"Reducing your existing EMIs by {fmt_inr(ceil_to(need, 100), 'ceil')}/month would bring your repayment ratio within limit.")
        if loan_type != "education" and not foir_ok and not other_fails and emp_type != "not_employed":
            # extra income must satisfy both FOIR and the income-multiple cap; round up with a margin
            req = (existing_emi + new_emi) / max_foir - income
            if "income_multiple_cap" in product:
                req = max(req, amount / product["income_multiple_cap"] - income)
            req = ceil_to(req + 1000, 1000)
            improvements.append(f"Adding an earning co-applicant with at least {fmt_inr(req, 'ceil')}/month income would make {fmt_inr(amount)} eligible.")
        elif amount > max_amount and loan_type != "education":
            pass  # the amount cap already explains itself via the 'qualify for up to' line
    if amount < min_amount:
        improvements.append(f"Request at least {fmt_inr(min_amount)}.")
    elif amount > max_amount and max_eligible < min_amount:
        improvements.append(f"Request an amount between {fmt_inr(min_amount)} and {fmt_inr(max_amount)}.")

    # --- Gauge
    hard_checks = [c for c in checks if c.hard]
    base = sum(1 for c in hard_checks if c.passed) / max(len(hard_checks), 1)
    pts = int(round(base * 100))
    pts = max(pts, 85) if status == "ELIGIBLE" else min(max(pts, 55), 80) if status == "CONDITIONAL" else min(pts, 45)

    # --- Summary
    lang = lang if lang in SUMMARY_T else "en"
    S = SUMMARY_T[lang]
    label = product["label"] if lang == "en" else LOAN_LABEL[loan_type][lang]
    slots = {"label": label, "amount": fmt_inr(amount), "tenure": f"{tenure:g}", "emi": fmt_inr(new_emi),
             "rate": rate, "min_amt": fmt_inr(min_amount), "max_amt": fmt_inr(max_eligible, "floor"),
             "emi_max": fmt_inr(emi(max_eligible, rate, tenure))}
    if status == "ELIGIBLE":
        summary = S["eligible"].format(**slots)
    elif status == "CONDITIONAL" and only_capacity_fails and amount < min_amount:
        summary = S["cond_min"].format(**slots)
    elif status == "CONDITIONAL" and only_capacity_fails:
        summary = S["cond_cap"].format(**slots)
    elif status == "CONDITIONAL":
        summary = S["cond_soft"].format(details="; ".join(c.detail for c in soft_flags), **slots)
    else:
        summary = S["not_el"].format(details="; ".join(c.detail for c in hard_fails[:3]), **slots)

    seen: set[str] = set()
    improvements = [i for i in improvements if not (i in seen or seen.add(i))]
    return Evaluation(status=status, loan_type=loan_type, checks=checks, invalid_fields=invalid,
                      emi=round(new_emi), foir=round(foir, 4) if math.isfinite(foir) else None,
                      interest_rate=rate, max_eligible_amount=max_eligible, requested_amount=amount, tenure_years=tenure,
                      improvements=improvements, summary=summary, score=pts)
