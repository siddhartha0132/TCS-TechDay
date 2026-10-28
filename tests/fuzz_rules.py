"""Property-based invariant fuzzer for backend/rules.py.

Run:  cd /Users/siddharthasinghal/TCS/loan-eligibility-chatbot && \
      .venv/bin/python /private/tmp/claude-501/-Users-siddharthasinghal-TCS/905345a8-5552-4a54-94dd-b0f9d04508bd/scratchpad/fuzz/rules_fuzz.py [N] [seed]
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _setup  # noqa: F401
import json, math, random, re, traceback
from collections import defaultdict

from backend.rules import evaluate, RULES, emi as engine_emi

N = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 1234
rng = random.Random(SEED)
ORDER = {"NOT_ELIGIBLE": 0, "CONDITIONAL": 1, "ELIGIBLE": 2}
AMOUNT_RULES = ("foir", "ltv", "income_multiple", "amount_range")

viol = defaultdict(int)
examples = defaultdict(list)
checked = defaultdict(int)


def flag(name, profile, msg):
    viol[name] += 1
    if len(examples[name]) < 3:
        examples[name].append((dict(profile), msg))


def parse_inr(s):
    s = s.strip()
    m = re.match(r"₹([\d,.]+)\s*(Cr|L)?", s)
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    return v * {"Cr": 1e7, "L": 1e5}.get(m.group(2), 1)


INR = r"(₹[\d,.]+(?:\s(?:Cr|L)\b)?)"


def std_emi(P, rate, years):
    n = max(int(round(years * 12)), 1)
    r = rate / 1200
    return P * r * (1 + r) ** n / ((1 + r) ** n - 1)


def pick(lo, hi, boundaries=()):
    if boundaries and rng.random() < 0.25:
        b = rng.choice(boundaries)
        return b + rng.choice([-1, 0, 0, 1]) * rng.choice([1, 0.01, 0.5])
    return rng.uniform(lo, hi)


def gen():
    lt = rng.choice(["personal", "home", "auto", "education"])
    pr = RULES["products"][lt]
    p = {"loan_type": lt}
    p["tenure_years"] = rng.choice([rng.randint(pr["min_tenure_years"], pr["max_tenure_years"]),
                                    rng.randint(pr["min_tenure_years"], pr["max_tenure_years"]),
                                    round(rng.uniform(0.5, pr["max_tenure_years"] + 5), 1)])
    hi_amt = pr.get("max_amount", pr.get("max_amount_abroad"))
    p["loan_amount"] = round(math.exp(rng.uniform(math.log(pr["min_amount"] * 0.5), math.log(hi_amt * 1.1))), -3)
    if lt == "education":
        p["age"] = rng.randint(15, 38)
        p["study_abroad"] = rng.random() < 0.5
        p["co_applicant_income"] = round(math.exp(rng.uniform(math.log(15000), math.log(500000))), -2)
        p["co_applicant_credit_score"] = rng.choice([rng.randint(550, 850), 650, 649, 679, 680])
        p["co_applicant_existing_emi"] = rng.choice([0, 0, round(rng.uniform(0, 0.5) * p["co_applicant_income"], -2)])
    else:
        p["employment_type"] = rng.choice(["salaried", "self_employed"])
        p["age"] = rng.choice([rng.randint(19, 66), 21, 20, 60, 59, 64, 65])
        p["monthly_income"] = round(math.exp(rng.uniform(math.log(15000), math.log(800000))), -2)
        p["credit_score"] = rng.choice([rng.randint(550, 850), pr["min_credit_score"], pr["min_credit_score"] - 1,
                                        pr["min_credit_score"] + 29, pr["min_credit_score"] + 30])
        p["existing_emi"] = rng.choice([0, 0, round(rng.uniform(0, 0.6) * p["monthly_income"], -2)])
        if rng.random() < 0.3:
            p["employment_months"] = rng.randint(0, 120)
        if rng.random() < 0.25:
            p["co_applicant_income"] = round(rng.uniform(10000, 200000), -2)
            p["co_applicant_existing_emi"] = rng.choice([0, round(rng.uniform(0, 30000), -2)])
        if lt == "home":
            p["property_value"] = round(p["loan_amount"] / rng.uniform(0.6, 1.1), -3)
        if lt == "auto":
            p["vehicle_price"] = round(p["loan_amount"] / rng.uniform(0.7, 1.05), -3)
    return p


def ev(p):
    return evaluate(p)


def hard_fails(e):
    return [c for c in e.checks if c.hard and not c.passed]


def failed_rules(e):
    return {c.rule for c in hard_fails(e)}


def run_one(p):
    e = ev(p)
    lt = p["loan_type"]
    pr = RULES["products"][lt]
    edu = lt == "education"
    inc_key = "co_applicant_income" if edu else "monthly_income"
    sc_key = "co_applicant_credit_score" if edu else "credit_score"
    emi_key = "co_applicant_existing_emi" if edu else "existing_emi"

    # I1 EMI formula
    checked["I1_emi_formula"] += 1
    t = min(max(p["tenure_years"], pr["min_tenure_years"]), pr["max_tenure_years"])
    exp_emi = std_emi(p["loan_amount"], pr["interest_rate"], t)
    if abs(e.emi - round(exp_emi)) > 1:
        flag("I1_emi_formula", p, f"emi {e.emi} vs {exp_emi:.0f}")

    # I2 FOIR formula
    checked["I2_foir_formula"] += 1
    inc = p[inc_key] + (0 if edu else p.get("co_applicant_income", 0) or 0)
    ex = p[emi_key] + (0 if edu or not p.get("co_applicant_income") else p.get("co_applicant_existing_emi", 0) or 0)
    exp_foir = (ex + exp_emi) / inc
    if abs(e.foir - exp_foir) > 0.0015:
        flag("I2_foir_formula", p, f"foir {e.foir} vs {exp_foir:.4f}")
    # I2b displayed (rounded) FOIR contradicts pass/fail of the check
    fo = next(c for c in e.checks if c.rule == "foir")
    checked["I2b_foir_display_vs_check"] += 1
    mm_f = re.search(r"Fixed-obligation ratio (just above )?([\d.]+)%", fo.detail)
    lim = round(pr["max_foir"] * 100, 1)
    shown = float(mm_f.group(2)) if mm_f else float("inf")
    above = bool(mm_f and mm_f.group(1))
    if mm_f and ((not fo.passed and shown <= lim and not above) or (fo.passed and (shown > lim or above))):
        flag("I2b_foir_display_vs_check", p, f"shown {shown}% limit {lim}% passed={fo.passed}: {fo.detail}")
    if lt == "home":
        lc = next(c for c in e.checks if c.rule == "ltv")
        checked["I2c_ltv_display_vs_check"] += 1
        mm = re.match(r"Loan-to-value (just above )?([\d.]+)% of .*? vs\. maximum (\d+)%", lc.detail)
        if mm and not lc.passed and not mm.group(1) and float(mm.group(2)) <= float(mm.group(3)):
            flag("I2c_ltv_display_vs_check", p, lc.detail)

    # I3 verdict classification consistency
    checked["I3_verdict_classification"] += 1
    hf = hard_fails(e)
    soft = [c for c in e.checks if not c.hard and not c.passed]
    if e.status == "ELIGIBLE" and (hf or soft):
        flag("I3_verdict_classification", p, "ELIGIBLE with failed checks")
    if e.status == "CONDITIONAL" and hf and not all(c.rule in AMOUNT_RULES for c in hf):
        flag("I3_verdict_classification", p, "CONDITIONAL with non-amount hard fail")
    if e.status == "NOT_ELIGIBLE" and not hf:
        flag("I3_verdict_classification", p, "NOT_ELIGIBLE with no hard fail")

    # I19 ELIGIBLE but max_eligible < requested (UI 'Max eligible' KPI smaller than an approved amount)
    checked["I19_eligible_but_max_below_request"] += 1
    if e.status == "ELIGIBLE" and e.max_eligible_amount < p["loan_amount"]:
        flag("I19_eligible_but_max_below_request", p, f"max {e.max_eligible_amount} < requested {p['loan_amount']}")

    def mono(name, q, cond=True):
        if not cond:
            return
        checked[name] += 1
        e2 = ev(q)
        if ORDER[e2.status] < ORDER[e.status]:
            flag(name, p, f"{e.status} -> {e2.status}; changed={ {k: q[k] for k in q if q.get(k) != p.get(k)} }; new fails={failed_rules(e2)}")

    mono("I4_monotone_income_up", {**p, inc_key: p[inc_key] * 1.5})
    mono("I5_monotone_score_up", {**p, sc_key: p[sc_key] + 50})
    mono("I6_monotone_existing_emi_down", {**p, emi_key: p[emi_key] * 0.5})
    mono("I7_monotone_amount_down", {**p, "loan_amount": p["loan_amount"] * 0.8}, p["loan_amount"] * 0.8 >= pr["min_amount"])
    if lt == "home":
        mono("I8_monotone_asset_up", {**p, "property_value": p["property_value"] * 1.3})
    if lt == "auto":
        mono("I8_monotone_asset_up", {**p, "vehicle_price": p["vehicle_price"] * 1.3})
    # tenure +1 within limits and within age-at-maturity
    t2 = t + 1
    if t2 <= pr["max_tenure_years"] and p["tenure_years"] >= pr["min_tenure_years"]:
        ok_age = edu or (p["age"] + t2 <= RULES["common"]["max_age_at_maturity"][p["employment_type"]])
        if ok_age:
            q = {**p, "tenure_years": t2}
            mono("I9a_monotone_tenure_up_verdict", q)
            checked["I9b_tenure_up_max_eligible"] += 1
            e2 = ev(q)
            if e2.max_eligible_amount < e.max_eligible_amount:
                flag("I9b_tenure_up_max_eligible", p, f"max {e.max_eligible_amount} -> {e2.max_eligible_amount}")

    # I10 max_eligible itself passes the amount checks (when nothing else fails)
    non_amount = [c for c in hf if c.rule not in AMOUNT_RULES]
    if not non_amount and e.max_eligible_amount >= pr["min_amount"]:
        checked["I10_max_eligible_is_eligible"] += 1
        e2 = ev({**p, "loan_amount": e.max_eligible_amount})
        bad = failed_rules(e2) & set(AMOUNT_RULES)
        if bad or e2.status == "NOT_ELIGIBLE":
            flag("I10_max_eligible_is_eligible", p, f"max_eligible {e.max_eligible_amount} re-evaluated -> {e2.status}, fails {bad}")

    # I11 CONDITIONAL summary 'eligible for up to X'
    m = re.search(r"up to " + INR, e.summary)
    if e.status == "CONDITIONAL" and m:
        X = parse_inr(m.group(1))
        checked["I11_summary_up_to_X_true"] += 1
        e2 = ev({**p, "loan_amount": X})
        if hard_fails(e2):
            e3 = ev({**p, "loan_amount": e.max_eligible_amount})
            sub = "_display_rounding" if not hard_fails(e3) else "_logic"
            flag("I11_summary_up_to_X_true" + sub, p, f"summary '{e.summary[:120]}' but {X} -> {e2.status} fails {failed_rules(e2)}")

    # Improvement suggestions. Each claim is checked on its OWN rule; a failure is classified as
    #   *_display_rounding : claim holds if the displayed ₹ figure is nudged by half a display step
    #                        (fmt_inr rounds L to ₹1,000 and Cr to ₹1 L, or the value sits exactly on the
    #                        limit and float error tips it over)
    #   *_logic            : claim is false regardless of rounding
    # and, separately, *_misleading_other_fails : the suggestion says "eligible" but some other hard
    # rule (score/age/income/LTV/amount range) still fails after applying it.
    def tol(X):
        return 50001 if X >= 1e7 else (501 if X >= 1e5 else 1)

    def claim(name, holds, X, favour):
        """holds(x)->bool; favour=+1 if a larger x should help, -1 if a smaller x should help."""
        checked[name] += 1
        if holds(X):
            return
        if holds(X + favour * tol(X)) or holds(X + favour * max(1.0, 1e-9 * X)):
            flag(name + "_display_rounding", p, last_msg[0])
        else:
            flag(name + "_logic", p, last_msg[0])

    last_msg = [""]
    for s in e.improvements:
        last_msg[0] = s
        m = re.search(r"Extending the tenure to ([\d.]+) years raises your eligibility to about " + INR, s)
        if m:
            N_, X = float(m.group(1)), parse_inr(m.group(2))
            def h(x, N_=N_):
                e2 = ev({**p, "tenure_years": N_, "loan_amount": x})
                return not (failed_rules(e2) & {"foir", "ltv", "income_multiple"})
            last_msg[0] = f"'{s}' -> at {N_}y amount {X}: fails {failed_rules(ev({**p, 'tenure_years': N_, 'loan_amount': X}))}"
            claim("I12_extend_tenure", h, X, -1)
            age_before = "age" in failed_rules(e)
            if not age_before and "age" in failed_rules(ev({**p, "tenure_years": N_})):
                flag("I12_extend_tenure_breaks_age", p, s)
        m = re.search(r"Reducing your existing EMIs by " + INR, s)
        if m:
            X = parse_inr(m.group(1))
            def h(x):
                q = dict(p); rem = x
                take = min(rem, q[emi_key]); q[emi_key] -= take; rem -= take
                if rem > 0 and not edu and q.get("co_applicant_existing_emi"):
                    q["co_applicant_existing_emi"] = max(q["co_applicant_existing_emi"] - rem, 0)
                return "foir" not in failed_rules(ev(q))
            last_msg[0] = f"'{s}' (FOIR {e.foir}, applicant EMI {p[emi_key]}, co-app EMI {p.get('co_applicant_existing_emi')})"
            claim("I13_close_emis", h, X, +1)
        m = re.search(r"Adding an earning co-applicant with at least " + INR + r"/month income would make " + INR + " eligible", s)
        if m:
            X = parse_inr(m.group(1))
            def q_of(x):
                q = dict(p)
                q["co_applicant_income"] = (q.get("co_applicant_income") or 0) + x
                return q
            last_msg[0] = f"'{s}' -> after adding {X}: foir {ev(q_of(X)).foir}"
            claim("I14_add_coapplicant", lambda x: "foir" not in failed_rules(ev(q_of(x))), X, +1)
            other = failed_rules(ev(q_of(X * 1.01 + 1000))) - {"foir"}
            if other:
                flag("I14_add_coapplicant_misleading_other_fails", p, f"'{s}' but still fails {other}")
        m = re.search(r"you qualify for up to " + INR + r" at ([\d.]+) years", s)
        if m:
            X = parse_inr(m.group(1))
            last_msg[0] = f"'{s}' (true max_eligible {e.max_eligible_amount})"
            claim("I15_qualify_up_to", lambda x: not (failed_rules(ev({**p, "loan_amount": x})) & set(AMOUNT_RULES)), X, -1)
        m = re.search(r"Reduce the tenure to ([\d.]+) years", s)
        if m:
            N_ = float(m.group(1))
            checked["I16_reduce_tenure"] += 1
            if "age" in failed_rules(ev({**p, "tenure_years": N_})):
                flag("I16_reduce_tenure_logic", p, s)
        m = re.search(r"Improve the credit score by ([\d.]+) points?", s)
        if m:
            checked["I17_improve_score"] += 1
            if "credit_score" in failed_rules(ev({**p, sc_key: p[sc_key] + float(m.group(1))})):
                flag("I17_improve_score_logic", p, s)
        m = re.search(r"Maximum loan at your income is " + INR, s)
        if m:
            X = parse_inr(m.group(1))
            last_msg[0] = f"'{s}' (exact cap {p[inc_key] + (p.get('co_applicant_income') or 0)}x)"
            claim("I18_income_multiple_cap", lambda x: "income_multiple" not in failed_rules(ev({**p, "loan_amount": x})), X, -1)
        m = re.search(r"request up to " + INR, s)
        if m:
            X = parse_inr(m.group(1))
            last_msg[0] = f"'{s}'"
            claim("I18b_ltv_request_up_to", lambda x: "ltv" not in failed_rules(ev({**p, "loan_amount": x})), X, -1)


crashes = 0
for i in range(N):
    p = gen()
    try:
        run_one(p)
    except Exception as exc:
        crashes += 1
        flag("I0_crash", p, f"{type(exc).__name__}: {exc}")

print(f"rules_fuzz: {N} random profiles, seed {SEED}, crashes {crashes}\n")
print(f"{'invariant':42s} {'checked':>8s} {'violations':>10s}")
for k in sorted(set(checked) | set(viol)):
    print(f"{k:42s} {checked.get(k, 0):8d} {viol.get(k, 0):10d}")
print()
for k in sorted(examples):
    print(f"=== {k}")
    for prof, msg in examples[k]:
        print("  profile:", json.dumps(prof))
        print("  ->", msg)

raise SystemExit(1 if (crashes or viol) else 0)
