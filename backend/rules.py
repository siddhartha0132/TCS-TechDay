"""Deterministic loan eligibility rules engine.

This is the *decision* half of the hybrid design: every eligibility verdict comes
from these auditable rules (loaded from data/rules.json), never from the LLM.
The LLM only extracts applicant facts and explains the result.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

RULES_PATH = Path(__file__).resolve().parent.parent / "data" / "rules.json"

LOAN_TYPES = ("personal", "home", "auto", "education")
EMPLOYMENT_TYPES = ("salaried", "self_employed")

# Fields the engine needs before it can give a verdict, per product.
REQUIRED_FIELDS: dict[str, list[str]] = {
    "personal": ["loan_amount", "tenure_years", "age", "monthly_income", "employment_type", "credit_score", "existing_emi"],
    "home": ["loan_amount", "tenure_years", "age", "monthly_income", "employment_type", "credit_score", "existing_emi", "property_value"],
    "auto": ["loan_amount", "tenure_years", "age", "monthly_income", "employment_type", "credit_score", "existing_emi", "vehicle_price"],
    "education": ["loan_amount", "tenure_years", "age", "study_abroad", "co_applicant_income", "co_applicant_credit_score", "co_applicant_existing_emi"],
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


def load_rules() -> dict[str, Any]:
    with open(RULES_PATH, encoding="utf-8") as f:
        return json.load(f)


RULES = load_rules()


# ---------------------------------------------------------------- helpers
def fmt_inr(amount: float | None) -> str:
    """Format in Indian style: ₹12.5 L / ₹1.2 Cr."""
    if amount is None:
        return "—"
    amount = float(amount)
    if amount >= 1e7:
        return f"₹{amount / 1e7:.2f} Cr".replace(".00", "")
    if amount >= 1e5:
        return f"₹{amount / 1e5:.2f} L".replace(".00", "")
    return f"₹{amount:,.0f}"


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
    if score is None:
        return "Unknown"
    for band in RULES["credit_score_bands"]:
        if score >= band["min"]:
            return band["label"]
    return "Poor"


def _ltv_cap(product: dict, amount: float) -> float:
    if "ltv_slabs" in product:
        for slab in product["ltv_slabs"]:
            if slab["upto"] is None or amount <= slab["upto"]:
                return slab["max_ltv"]
    return product.get("max_ltv", 1.0)


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
        d["max_eligible_display"] = fmt_inr(self.max_eligible_amount) if self.max_eligible_amount else None
        d["requested_display"] = fmt_inr(self.requested_amount) if self.requested_amount else None
        return d


# ---------------------------------------------------------------- normalisation
def normalize_profile(raw: dict[str, Any]) -> dict[str, Any]:
    """Coerce loosely-typed applicant data into the shape the engine expects.

    Handles strings like "12,50,000", "8.5 lakh", "salaried", "yes/no".
    """
    out: dict[str, Any] = {}
    for key, val in (raw or {}).items():
        if val is None or val == "":
            continue
        if key == "loan_type":
            v = str(val).strip().lower()
            alias = {"car": "auto", "vehicle": "auto", "two-wheeler": "auto", "housing": "home", "house": "home",
                     "mortgage": "home", "study": "education", "student": "education"}
            out[key] = alias.get(v, v)
        elif key == "employment_type":
            v = str(val).strip().lower().replace("-", "_").replace(" ", "_")
            if v in ("self_employed", "business", "businessman", "freelancer", "professional", "self"):
                out[key] = "self_employed"
            elif v in ("salaried", "employee", "job", "service"):
                out[key] = "salaried"
            else:
                out[key] = v
        elif key == "study_abroad":
            if isinstance(val, bool):
                out[key] = val
            else:
                out[key] = str(val).strip().lower() in ("true", "yes", "abroad", "foreign", "overseas", "1")
        else:
            out[key] = parse_amount(val)
    return out


def parse_amount(val: Any) -> Optional[float]:
    """'12,50,000' -> 1250000; '8.5 lakh' -> 850000; '1.2 cr' -> 12000000; '45k' -> 45000."""
    if isinstance(val, bool):
        return float(val)
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().lower().replace(",", "").replace("₹", "").replace("rs.", "").replace("rs", "").replace("inr", "")
    s = s.strip()
    mult = 1.0
    for suffix, m in (("crore", 1e7), ("cr", 1e7), ("lakhs", 1e5), ("lakh", 1e5), ("lac", 1e5), ("l", 1e5), ("k", 1e3)):
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()
            mult = m
            break
    try:
        return float(s) * mult
    except ValueError:
        return None


# ---------------------------------------------------------------- the engine
def evaluate(profile_in: dict[str, Any]) -> Evaluation:
    p = normalize_profile(profile_in)
    loan_type = p.get("loan_type")
    if loan_type not in LOAN_TYPES:
        return Evaluation(status="INCOMPLETE", loan_type=loan_type or "", missing_fields=["loan_type"],
                          summary="I need to know which loan you are looking for: personal, home, car or education.")

    missing = [f for f in REQUIRED_FIELDS[loan_type] if p.get(f) is None]
    if missing:
        return Evaluation(status="INCOMPLETE", loan_type=loan_type, missing_fields=missing,
                          summary="A few more details are needed before I can check eligibility.")

    product = RULES["products"][loan_type]
    common = RULES["common"]
    checks: list[Check] = []
    improvements: list[str] = []

    amount = float(p["loan_amount"])
    tenure = float(p["tenure_years"])
    age = float(p["age"])
    rate = product["interest_rate"]

    # --- Education loans are underwritten on the co-applicant (parent/guardian)
    if loan_type == "education":
        income = float(p["co_applicant_income"])
        score = float(p["co_applicant_credit_score"])
        existing_emi = float(p["co_applicant_existing_emi"])
        emp_type = "salaried"
        who = "Co-applicant"
    else:
        income = float(p["monthly_income"])
        score = float(p["credit_score"])
        existing_emi = float(p["existing_emi"])
        emp_type = p.get("employment_type", "salaried")
        if emp_type not in EMPLOYMENT_TYPES:
            emp_type = "salaried"
        who = "Applicant"
        # Optional co-applicant (spouse/parent): incomes and obligations are clubbed for repayment capacity
        if p.get("co_applicant_income"):
            income += float(p["co_applicant_income"])
            existing_emi += float(p.get("co_applicant_existing_emi") or 0)
            who = "Combined"

    # 1. Tenure within product limits (clamp silently for the EMI maths, flag if outside)
    if tenure < product["min_tenure_years"] or tenure > product["max_tenure_years"]:
        clamped = min(max(tenure, product["min_tenure_years"]), product["max_tenure_years"])
        checks.append(Check("tenure_range", False,
                            f"Tenure must be between {product['min_tenure_years']} and {product['max_tenure_years']} years; "
                            f"you asked for {tenure:g}, so I evaluated at {clamped:g} years.", hard=False))
        improvements.append(f"Choose a tenure between {product['min_tenure_years']} and {product['max_tenure_years']} years.")
        tenure = clamped
    else:
        checks.append(Check("tenure_range", True, f"Tenure of {tenure:g} years is within the allowed {product['min_tenure_years']}–{product['max_tenure_years']} years."))

    # 2. Age
    if loan_type == "education":
        lo, hi = product["student_min_age"], product["student_max_age"]
        ok = lo <= age <= hi
        checks.append(Check("age", ok, f"Student age {age:g} is {'within' if ok else 'outside'} the {lo}–{hi} range."))
        if not ok:
            improvements.append(f"Education loans are offered to students aged {lo}–{hi}.")
    else:
        max_at_maturity = common["max_age_at_maturity"][emp_type]
        age_at_maturity = age + tenure
        if age < common["min_age"]:
            checks.append(Check("age", False, f"Minimum age is {common['min_age']} (you are {age:g})."))
            improvements.append(f"You can apply once you turn {common['min_age']}.")
        elif age_at_maturity > max_at_maturity:
            max_tenure_by_age = max(max_at_maturity - age, 0)
            checks.append(Check("age", False,
                                f"Age at loan maturity would be {age_at_maturity:g}; the limit is {max_at_maturity} for {emp_type.replace('_', '-')} applicants."))
            if max_tenure_by_age >= product["min_tenure_years"]:
                improvements.append(f"Reduce the tenure to {max_tenure_by_age:g} years so the loan closes before age {max_at_maturity}.")
            else:
                improvements.append("Consider adding a younger co-applicant.")
        else:
            checks.append(Check("age", True, f"Age {age:g} with maturity at {age_at_maturity:g} is within the limit of {max_at_maturity}."))

    # 3. Employment vintage (optional fields, only checked when supplied)
    if loan_type != "education":
        emp_months = p.get("employment_months")
        min_months = common["min_employment_months"][emp_type]
        if emp_months is not None:
            ok = emp_months >= min_months
            checks.append(Check("employment_vintage", ok,
                                f"{emp_months:g} months of {emp_type.replace('_', '-')} experience vs. minimum {min_months}."))
            if not ok:
                improvements.append(f"Apply after {min_months - emp_months:g} more months of work history.")

    # 4. Minimum income
    if loan_type == "education":
        min_income = product["min_co_applicant_income"]
    else:
        min_income = product["min_monthly_income"][emp_type]
    ok = income >= min_income
    checks.append(Check("min_income", ok, f"{who} net income {fmt_inr(income)}/month vs. minimum {fmt_inr(min_income)}."))
    if not ok:
        improvements.append(f"Minimum income for this product is {fmt_inr(min_income)}/month; a co-applicant's income can be added.")

    # 5. Credit score
    min_score = product["min_credit_score"]
    ok = score >= min_score
    score_owner = "Co-applicant" if loan_type == "education" else "Applicant"
    checks.append(Check("credit_score", ok, f"{score_owner} credit score {score:g} ({credit_band(score)}) vs. minimum {min_score}."))
    if not ok:
        improvements.append(f"Improve the credit score by {min_score - score:g} points (pay EMIs/cards on time, keep card utilisation under 30%, avoid new hard enquiries).")
    elif score < min_score + 30:
        checks.append(Check("credit_score_margin", False, f"Score is close to the cut-off; a stronger score would get a better rate.", hard=False))

    # 6. Amount within product bounds
    if loan_type == "education":
        max_amount = product["max_amount_abroad"] if p.get("study_abroad") else product["max_amount_india"]
    else:
        max_amount = product["max_amount"]
    min_amount = product["min_amount"]
    if amount < min_amount or amount > max_amount:
        checks.append(Check("amount_range", False, f"Amount must be between {fmt_inr(min_amount)} and {fmt_inr(max_amount)} for this product."))
        improvements.append(f"Request an amount between {fmt_inr(min_amount)} and {fmt_inr(max_amount)}.")
    else:
        checks.append(Check("amount_range", True, f"Requested {fmt_inr(amount)} is within the product range."))

    # 7. Collateral / LTV
    ltv_limit_amount: Optional[float] = None
    if loan_type == "home":
        pv = float(p["property_value"])
        cap = _ltv_cap(product, amount)
        ltv_limit_amount = pv * cap
        ok = amount <= ltv_limit_amount
        checks.append(Check("ltv", ok, f"Loan-to-value {amount / pv:.0%} vs. maximum {cap:.0%} for this slab ({fmt_inr(ltv_limit_amount)} on a {fmt_inr(pv)} property)."))
        if not ok:
            improvements.append(f"Increase your down payment by {fmt_inr(amount - ltv_limit_amount)} (or request up to {fmt_inr(ltv_limit_amount)}).")
    elif loan_type == "auto":
        vp = float(p["vehicle_price"])
        cap = product["max_ltv"]
        ltv_limit_amount = vp * cap
        ok = amount <= ltv_limit_amount
        checks.append(Check("ltv", ok, f"Financing {amount / vp:.0%} of on-road price vs. maximum {cap:.0%} ({fmt_inr(ltv_limit_amount)})."))
        if not ok:
            improvements.append(f"Increase the down payment by {fmt_inr(amount - ltv_limit_amount)}.")
    elif loan_type == "education" and amount > product["requires_collateral_above"]:
        checks.append(Check("collateral", False,
                            f"Loans above {fmt_inr(product['requires_collateral_above'])} need collateral (property, FD or LIC policy).", hard=False))

    # 8. Repayment capacity: FOIR = (existing EMIs + new EMI) / income
    new_emi = emi(amount, rate, tenure)
    foir = (existing_emi + new_emi) / income if income else 1.0
    max_foir = product["max_foir"]
    ok = foir <= max_foir
    checks.append(Check("foir", ok,
                        f"Fixed-obligation ratio {foir:.0%} (existing {fmt_inr(existing_emi)} + new EMI {fmt_inr(new_emi)} on {fmt_inr(income)} income) vs. limit {max_foir:.0%}."))

    # Max eligible amount at this tenure, given FOIR, multiplier, product and LTV caps
    headroom = max(income * max_foir - existing_emi, 0)
    by_foir = max_principal_for_emi(headroom, rate, tenure)
    caps = [by_foir, max_amount]
    if "income_multiple_cap" in product:
        caps.append(income * product["income_multiple_cap"])
    if ltv_limit_amount is not None:
        caps.append(ltv_limit_amount)
    max_eligible = math.floor(min(caps) / 10000) * 10000

    if not ok:
        # Counterfactuals: what would make this work?
        if max_eligible >= min_amount:
            improvements.append(f"Based on your repayment capacity you qualify for up to {fmt_inr(max_eligible)} at {tenure:g} years.")
        longest = product["max_tenure_years"]
        if loan_type != "education":
            longest = min(longest, common["max_age_at_maturity"][emp_type] - age)
        if longest > tenure:
            by_foir_long = max_principal_for_emi(headroom, rate, longest)
            alt = math.floor(min([by_foir_long] + caps[1:]) / 10000) * 10000
            if alt > max_eligible:
                improvements.append(f"Extending the tenure to {longest:g} years raises your eligibility to about {fmt_inr(alt)}.")
        emi_to_close = (existing_emi + new_emi) - income * max_foir
        if existing_emi > 0 and emi_to_close > 0:
            improvements.append(f"Closing existing EMIs worth {fmt_inr(min(emi_to_close, existing_emi))}/month would bring your FOIR within limit.")
        extra_income = (existing_emi + new_emi) / max_foir - income
        improvements.append(f"Adding a co-applicant with {fmt_inr(extra_income)}/month income would also make {fmt_inr(amount)} eligible.")
    elif foir > max_foir - 0.05:
        checks.append(Check("foir_margin", False, "Repayment ratio is close to the limit; keep other borrowings low until disbursal.", hard=False))

    # 9. Income multiplier cap (unsecured products)
    if "income_multiple_cap" in product and loan_type != "education":
        cap_amount = income * product["income_multiple_cap"]
        ok = amount <= cap_amount
        checks.append(Check("income_multiple", ok,
                            f"Requested amount is {amount / income:.0f}× monthly income vs. cap of {product['income_multiple_cap']}× ({fmt_inr(cap_amount)})."))
        if not ok:
            improvements.append(f"Maximum loan at your income is {fmt_inr(cap_amount)} ({product['income_multiple_cap']}× monthly income).")

    # --- Verdict
    hard_fails = [c for c in checks if c.hard and not c.passed]
    soft_flags = [c for c in checks if not c.hard and not c.passed]
    only_amount_fails = hard_fails and all(c.rule in ("foir", "ltv", "income_multiple", "amount_range") for c in hard_fails)

    if not hard_fails:
        status = "CONDITIONAL" if soft_flags else "ELIGIBLE"
    elif only_amount_fails and max_eligible >= min_amount:
        status = "CONDITIONAL"
    else:
        status = "NOT_ELIGIBLE"

    # Eligibility strength (for the gauge): share of hard checks passed, weighted by margins
    hard_checks = [c for c in checks if c.hard]
    base = sum(1 for c in hard_checks if c.passed) / max(len(hard_checks), 1)
    score_pts = int(round(base * 100))
    if status == "ELIGIBLE":
        score_pts = max(score_pts, 85)
    elif status == "CONDITIONAL":
        score_pts = min(max(score_pts, 55), 80)
    else:
        score_pts = min(score_pts, 45)

    # Summary line
    if status == "ELIGIBLE":
        summary = f"You are eligible for a {product['label']} of {fmt_inr(amount)} over {tenure:g} years. Indicative EMI: {fmt_inr(new_emi)}/month at {rate}% p.a."
    elif status == "CONDITIONAL" and only_amount_fails and amount < min_amount:
        summary = (f"The minimum {product['label']} is {fmt_inr(min_amount)}; you are eligible for anything from {fmt_inr(min_amount)} "
                   f"up to {fmt_inr(max_eligible)} over {tenure:g} years.")
    elif status == "CONDITIONAL" and only_amount_fails:
        summary = (f"{fmt_inr(amount)} is above what you qualify for, but you are eligible for up to {fmt_inr(max_eligible)} "
                   f"over {tenure:g} years (EMI about {fmt_inr(emi(max_eligible, rate, tenure))}/month).")
    elif status == "CONDITIONAL":
        summary = f"You are eligible for {fmt_inr(amount)} over {tenure:g} years, subject to: " + "; ".join(c.detail for c in soft_flags)
    else:
        summary = f"You are not eligible for a {product['label']} of {fmt_inr(amount)} right now. Main reasons: " + "; ".join(c.detail for c in hard_fails[:3])

    # de-duplicate improvements preserving order
    seen = set()
    improvements = [i for i in improvements if not (i in seen or seen.add(i))]

    return Evaluation(status=status, loan_type=loan_type, checks=checks, emi=round(new_emi), foir=round(foir, 3),
                      interest_rate=rate, max_eligible_amount=max_eligible, requested_amount=amount, tenure_years=tenure,
                      improvements=improvements, summary=summary, score=score_pts)
