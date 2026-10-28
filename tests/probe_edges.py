"""Edge-value / garbage-input probe for rules.evaluate and normalize_profile (/api/evaluate path)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _setup  # noqa: F401
import json

from backend.rules import evaluate, parse_amount, normalize_profile

BASE = {
    "personal": {"loan_type": "personal", "loan_amount": 500000, "tenure_years": 3, "age": 30, "monthly_income": 80000,
                 "employment_type": "salaried", "credit_score": 780, "existing_emi": 0},
    "home": {"loan_type": "home", "loan_amount": 2500000, "tenure_years": 20, "age": 35, "monthly_income": 120000,
             "employment_type": "salaried", "credit_score": 780, "existing_emi": 0, "property_value": 4000000},
    "auto": {"loan_type": "auto", "loan_amount": 600000, "tenure_years": 5, "age": 30, "monthly_income": 60000,
             "employment_type": "salaried", "credit_score": 780, "existing_emi": 0, "vehicle_price": 800000},
    "education": {"loan_type": "education", "loan_amount": 500000, "tenure_years": 10, "age": 22, "study_abroad": False,
                  "co_applicant_income": 80000, "co_applicant_credit_score": 780, "co_applicant_existing_emi": 0},
}


def strict_json(d):
    """Starlette's JSONResponse uses allow_nan=False -> NaN/inf in the payload is a 500."""
    json.dumps(d, allow_nan=False)


def run(label, prof):
    try:
        ev = evaluate(prof)
        d = ev.as_dict()
        try:
            strict_json(d)
            js = "ok"
        except ValueError as exc:
            js = f"JSON-FAIL({exc})"
        print(f"{label:60s} -> {ev.status:13s} emi={d['emi']} foir={d['foir']} max={d['max_eligible_amount']} json={js}")
        return ev
    except Exception as exc:
        print(f"{label:60s} -> CRASH {type(exc).__name__}: {exc}")


print("== parse_amount on strings an LLM / integration might send")
for s in ["5 lakh", "5 lakhs", "5 lacs", "5 Lac", "2 crore", "2 crores", "1.2 cr", "45k", "45K", "50 thousand", "70 hazaar",
          "5,00,000/-", "Rs 45,000 pm", "₹45,000 per month", "5 lakh rupees", "five lakh", "-5 lakh", "1e9", "nan", "inf",
          "abc", "12 LPA", "1.5L", "40 लाख", "७५०", "750+", "around 750", "~780", "0x10", "1_000_000"]:
    print(f"  {s!r:22s} -> {parse_amount(s)!r}")

print("\n== normalize_profile categorical values")
for v in ["Personal Loan", "car loan", "Home", "two wheeler", "LAP"]:
    print(f"  loan_type {v!r:18s} -> {normalize_profile({'loan_type': v}).get('loan_type')!r}  status={evaluate({**BASE['personal'], 'loan_type': v}).status}")
for v in ["Self-Employed Professional", "unemployed", "student", "retired", "housewife", "Salaried (govt)", "self employed"]:
    n = normalize_profile({"employment_type": v}).get("employment_type")
    print(f"  employment_type {v!r:30s} -> {n!r}  status={evaluate({**BASE['personal'], 'employment_type': v}).status}")
for v in ["yes", "Yes", "y", "Y", "USA", "us", "UK", "abroad - USA", "true", "no", "India", "overseas (Canada)"]:
    print(f"  study_abroad {v!r:20s} -> {normalize_profile({'study_abroad': v}).get('study_abroad')!r}")

print("\n== numeric edge values (each field set on a clean ELIGIBLE base)")
vals = [0, -1, -500000, float("nan"), float("inf"), "nan", "inf", "-5 lakh", "1e9", "abc", 1e308]
for lt, base in BASE.items():
    fields = [k for k in base if k not in ("loan_type", "employment_type", "study_abroad")]
    for f in fields:
        for v in vals:
            run(f"{lt}.{f}={v!r}", {**base, f: v})

print("\n== boundaries")
run("personal age 21 exactly", {**BASE["personal"], "age": 21})
run("personal age 20.99", {**BASE["personal"], "age": 20.99})
run("personal age 57 + tenure 3 = 60 exactly", {**BASE["personal"], "age": 57})
run("personal score 700 exactly", {**BASE["personal"], "credit_score": 700})
run("personal score 9999 (out of 300-900 range)", {**BASE["personal"], "credit_score": 9999})
run("personal score 5 lakh (wrong-field answer)", {**BASE["personal"], "credit_score": 500000})
run("personal score 0", {**BASE["personal"], "credit_score": 0})
run("personal age 250", {**BASE["personal"], "age": 250})
run("personal tenure 0", {**BASE["personal"], "tenure_years": 0})
run("personal tenure 500000 (wrong-field answer)", {**BASE["personal"], "tenure_years": 500000})
run("personal existing_emi negative -50000", {**BASE["personal"], "existing_emi": -50000, "monthly_income": 26000, "loan_amount": 600000})
run("personal income 0 with co-applicant 80k", {**BASE["personal"], "monthly_income": 0, "co_applicant_income": 80000})
run("education abroad=False 1 Cr", {**BASE["education"], "loan_amount": 1e7})
run("education abroad='y' 1 Cr", {**BASE["education"], "loan_amount": 1e7, "study_abroad": "y"})
run("education age 16", {**BASE["education"], "age": 16})
run("personal employment_months=0", {**BASE["personal"], "employment_months": 0})
run("personal + co_applicant_income=0", {**BASE["personal"], "co_applicant_income": 0, "co_applicant_existing_emi": 99999})
run("personal + co_applicant_existing_emi only (no income)", {**BASE["personal"], "co_applicant_existing_emi": 99999})
run("bool True as amount", {**BASE["personal"], "loan_amount": True})
