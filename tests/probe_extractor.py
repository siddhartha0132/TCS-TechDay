"""Realistic-message probe for backend/extractor.extract (free-form and direct-answer modes).

Each case: (text, expected_field or None, loan_type context or None, {field: expected value}, forbidden fields)
A value of ABSENT means the field must NOT be extracted.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _setup  # noqa: F401

from backend.extractor import extract

ABSENT = object()
L, CR, K = 1e5, 1e7, 1e3

CASES = [
    # ---- annual vs monthly income
    ("I earn 12 LPA, need a personal loan of 5 lakh for 3 years", None, None, {"monthly_income": 1e5, "loan_amount": 5 * L}),
    ("My annual income is 12 lakh. Personal loan of 5 lakh for 3 years", None, None, {"monthly_income": 1e5}),
    ("salary 18 lakh per annum, want home loan 50 lakh", None, None, {"monthly_income": 1.5 * L, "loan_amount": 50 * L}),
    ("My CTC is 18 lakh, need a car loan of 8 lakh", None, None, {"monthly_income": ABSENT, "loan_amount": 8 * L}),
    ("I make 9.6 lakh a year", None, None, {"monthly_income": 80000}),
    ("income 1.2 lakh per month", None, None, {"monthly_income": 1.2 * L}),
    # ---- number formats
    ("Need Rs. 5,00,000/- personal loan", None, None, {"loan_amount": 5 * L}),
    ("need 1.5L personal loan", None, None, {"loan_amount": 1.5 * L}),
    ("need 2 cr home loan", None, None, {"loan_amount": 2 * CR}),
    ("need 2 crores for a house", None, None, {"loan_amount": 2 * CR}),
    ("home loan of 1.2cr", None, None, {"loan_amount": 1.2 * CR}),
    ("loan 5 lacs personal", None, None, {"loan_amount": 5 * L}),
    ("mera salary 50 hazar hai", None, None, {"monthly_income": 50 * K}),
    ("मेरी सैलरी ५०००० है", None, None, {"monthly_income": 50000}),
    ("मुझे ४० लाख का होम लोन चाहिए", None, None, {"loan_amount": 40 * L, "loan_type": "home"}),
    ("मुझे 2 करोड़ का होम लोन चाहिए", None, None, {"loan_amount": 2 * CR}),  # decomposed nukta
    ("मुझे 2 करोड़ का होम लोन चाहिए", None, None, {"loan_amount": 2 * CR}),  # precomposed ड़ (U+095C)
    ("मेरी सैलरी 70 हज़ार है", None, None, {"monthly_income": 70 * K}),  # precomposed ज़ (U+095B)
    ("need personal loan 5-6 lakh", None, None, {"loan_amount": 5 * L}),
    ("I need around 5 to 6 lakh as a personal loan", None, None, {"loan_amount": 5 * L}),
    ("salary is ₹45k", None, None, {"monthly_income": 45 * K}),
    ("i earn 1,20,000 monthly", None, None, {"monthly_income": 1.2 * L}),
    # ---- tenure
    ("personal loan 5 lakh, 5yrs", None, None, {"tenure_years": 5}),
    ("personal loan 5 lakh for 60 months", None, None, {"tenure_years": 5}),
    ("I want a 20-year home loan of 40 lakh", None, None, {"tenure_years": 20}),
    ("I have 8 years of experience and need a personal loan of 5 lakh", None, None, {"tenure_years": ABSENT}),
    ("I am 30 years old, working for 6 years, need 5 lakh for 3 years", None, None, {"age": 30, "tenure_years": 3}),
    ("I joined my company 8 months ago, need a personal loan of 2 lakh", None, None, {"tenure_years": ABSENT}),
    # ---- age
    ("29 y/o, need personal loan 3 lakh", None, None, {"age": 29}),
    ("Age: 34. Salary 70000", None, None, {"age": 34}),
    ("I'm 30 and my wife is 28", None, None, {"age": 30}),
    # ---- credit score
    ("CIBIL 780, salary 60k", None, None, {"credit_score": 780}),
    ("my score is 800+", None, None, {"credit_score": 800}),
    ("My father's CIBIL is 750", None, "education", {"co_applicant_credit_score": 750}),
    # ---- EMIs and negation
    ("No car loan but I pay 5k credit card EMI", None, "personal", {"existing_emi": 5 * K}),
    ("I don't have any EMIs. Salary 80k", None, "personal", {"existing_emi": 0, "monthly_income": 80 * K}),
    ("I'm not paying any EMI right now, salary 60000", None, "personal", {"existing_emi": 0, "monthly_income": 60000}),
    ("I pay 15000 per month as EMI and earn 60k", None, "personal", {"existing_emi": 15000, "monthly_income": 60000}),
    ("EMI of 12k on my bike, salary 45k", None, "personal", {"existing_emi": 12000, "monthly_income": 45000}),
    ("koi EMI nahi hai, salary 40 hazaar", None, "personal", {"existing_emi": 0, "monthly_income": 40000}),
    # ---- income disambiguation
    ("My wife earns 40k and I earn 60k", None, "home", {"monthly_income": 60000, "co_applicant_income": 40000}),
    ("Need 5 lakh personal loan, salary 50k", None, None, {"loan_amount": 5 * L, "monthly_income": 50000}),
    ("salary 50k, need 50k personal loan", None, None, {"loan_amount": 50000, "monthly_income": 50000}),
    ("I have 10 lakh in FD and need a personal loan, salary 60k", None, None, {"loan_amount": ABSENT}),
    ("sorry my salary is 80k not 60k", None, "personal", {"monthly_income": 80000, "loan_amount": ABSENT}),
    ("sorry, I meant 8 lakh", None, "personal", {"loan_amount": 8 * L}),
    # ---- loan type detection
    ("I want to buy a car, need 8 lakh", None, None, {"loan_type": "auto"}),
    ("I want a new home, need 40 lakh", None, None, {"loan_type": "home"}),
    ("Of course, my salary is 50k", None, "home", {"loan_type": ABSENT}),
    ("my father has a car loan EMI of 10k", None, "education", {"loan_type": ABSENT, "co_applicant_existing_emi": 10000}),
    ("I pay 8000 EMI on my home loan", None, "personal", {"loan_type": ABSENT, "existing_emi": 8000}),
    ("I live in my own house, salary 60k", None, "auto", {"loan_type": ABSENT}),
    ("We are going to America for my MS", None, None, {"employment_type": ABSENT, "study_abroad": True}),
    # ---- employment
    ("I work as a consultant at Accenture", None, "personal", {"employment_type": "salaried"}),
    ("I am a doctor at AIIMS, salaried", None, "personal", {"employment_type": "salaried"}),
    ("I lost my job last month", None, "personal", {"employment_type": "not_employed"}),
    ("I am unemployed", "employment_type", "personal", {"employment_type": "not_employed"}),
    ("I'm a retired government employee getting pension", "employment_type", "personal", {"employment_type": "not_employed"}),
    ("I travel for business a lot but I'm an engineer at TCS", None, "personal", {"employment_type": "salaried"}),
    # ---- direct answers to the slot just asked
    ("I am 30", "loan_amount", "personal", {"loan_amount": ABSENT}),
    ("salary 50k", "age", "personal", {"age": ABSENT, "monthly_income": 50000}),
    ("CIBIL 750", "monthly_income", "personal", {"monthly_income": ABSENT, "credit_score": 750}),
    ("5 lakh", "credit_score", "personal", {"credit_score": ABSENT}),
    ("age 30", "tenure_years", "personal", {"tenure_years": ABSENT, "age": 30}),
    ("0", "monthly_income", "personal", {"monthly_income": ABSENT}),
    ("50", "monthly_income", "personal", {"monthly_income": ABSENT}),
    ("5", "loan_amount", "personal", {"loan_amount": ABSENT}),
    ("5000, no other loans", "existing_emi", "personal", {"existing_emi": 5000}),
    ("No car loan but 5k credit card EMI", "existing_emi", "personal", {"existing_emi": 5000}),
    ("In India, IIM Ahmedabad", "study_abroad", "education", {"study_abroad": False}),
    ("India, thanks", "study_abroad", "education", {"study_abroad": False}),
    ("Bharat mein", "study_abroad", "education", {"study_abroad": False}),
    ("Pune, Maharashtra", "study_abroad", "education", {"study_abroad": False}),
    ("Not abroad, in India", "study_abroad", "education", {"study_abroad": False}),
    ("a business school in Bangalore", "study_abroad", "education", {"study_abroad": False}),
    ("5 years 6 months", "tenure_years", "personal", {"tenure_years": 5.5}),
    ("2.5 yrs", "tenure_years", "personal", {"tenure_years": 2.5}),
    ("he pays 12k for a car loan", "co_applicant_existing_emi", "education", {"loan_type": ABSENT, "co_applicant_existing_emi": 12000}),
    ("around 25k", "monthly_income", "personal", {"monthly_income": 25000}),
    ("Rs 45,000 per month", "monthly_income", "personal", {"monthly_income": 45000}),
    ("abt 750 i think", "credit_score", "personal", {"credit_score": 750}),
]


def close(a, b):
    if isinstance(b, bool) or isinstance(a, bool):
        return a is b
    if isinstance(b, (int, float)) and isinstance(a, (int, float)):
        return abs(a - b) <= max(1.0, 0.01 * abs(b))
    return str(a) == str(b)


fails = 0
for text, ef, lt, exp in CASES:
    got = extract(text, ef, lt)
    bad = []
    for k, v in exp.items():
        if v is ABSENT:
            if k in got:
                bad.append(f"{k}: expected absent, got {got[k]!r}")
        elif k not in got:
            bad.append(f"{k}: expected {v!r}, MISSING")
        elif not close(got[k], v):
            bad.append(f"{k}: expected {v!r}, got {got[k]!r}")
    if bad:
        fails += 1
        ctx = f"[asked={ef}, ctx={lt}]" if (ef or lt) else ""
        print(f"FAIL {text!r} {ctx}\n     got={got}\n     " + "; ".join(bad))
print(f"\nextractor_probe: {len(CASES)} cases, {fails} failing")
raise SystemExit(1 if fails else 0)
