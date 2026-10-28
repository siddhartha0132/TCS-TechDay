"""Generate a synthetic applicant dataset (no real customer data).

Usage:  python -m data.generate_synthetic --n 300 --seed 7
Writes data/applicants.csv with the engine's verdict for each row so the
dataset doubles as a regression fixture and a demo pool.
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.rules import evaluate  # noqa: E402

OUT = Path(__file__).resolve().parent / "applicants.csv"
COLUMNS = ["id", "loan_type", "loan_amount", "tenure_years", "age", "monthly_income", "employment_type", "employment_months",
           "credit_score", "existing_emi", "property_value", "vehicle_price", "study_abroad", "co_applicant_income",
           "co_applicant_credit_score", "co_applicant_existing_emi", "expected_status", "max_eligible_amount", "emi"]


def rnd_score(r: random.Random) -> int:
    # Skewed toward 700-800 like a real retail book, with a tail of thin/poor files
    return int(min(900, max(300, r.gauss(730, 55))))


def gen_one(r: random.Random, i: int) -> dict:
    loan_type = r.choices(["personal", "home", "auto", "education"], weights=[40, 25, 20, 15])[0]
    emp = r.choices(["salaried", "self_employed"], weights=[70, 30])[0]
    income = int(round(r.lognormvariate(10.9, 0.5) / 1000) * 1000)  # median ~₹54k
    row = dict(id=f"SYN{i:04d}", loan_type=loan_type, employment_type=emp, monthly_income=income,
               employment_months=r.choice([4, 9, 14, 24, 36, 60, 96, 150]), credit_score=rnd_score(r),
               existing_emi=r.choice([0, 0, 0, 3000, 8000, 12000, 20000, 35000]),
               property_value="", vehicle_price="", study_abroad="", co_applicant_income="",
               co_applicant_credit_score="", co_applicant_existing_emi="")
    if loan_type == "personal":
        row.update(age=r.randint(21, 62), tenure_years=r.randint(1, 6), loan_amount=r.choice([100000, 200000, 300000, 500000, 800000, 1200000, 2000000, 3500000]))
    elif loan_type == "home":
        pv = r.choice([2500000, 4000000, 6000000, 8000000, 12000000, 20000000])
        row.update(age=r.randint(24, 55), tenure_years=r.choice([10, 15, 20, 25, 30]), property_value=pv,
                   loan_amount=int(pv * r.choice([0.6, 0.75, 0.8, 0.85, 0.9, 0.95]) // 10000 * 10000))
    elif loan_type == "auto":
        vp = r.choice([500000, 800000, 1000000, 1500000, 2500000])
        row.update(age=r.randint(21, 58), tenure_years=r.randint(1, 8), vehicle_price=vp,
                   loan_amount=int(vp * r.choice([0.7, 0.8, 0.9, 0.95]) // 10000 * 10000))
    else:
        abroad = r.random() < 0.45
        row.update(age=r.randint(17, 38), tenure_years=r.choice([5, 7, 10, 12, 15]), study_abroad=abroad,
                   loan_amount=r.choice([400000, 700000, 1500000, 2500000, 4000000] if not abroad else [2000000, 4000000, 6000000, 10000000]),
                   co_applicant_income=int(round(r.lognormvariate(11.1, 0.5) / 1000) * 1000),
                   co_applicant_credit_score=rnd_score(r), co_applicant_existing_emi=r.choice([0, 0, 5000, 15000, 30000]),
                   monthly_income="", existing_emi="", employment_months="")
    ev = evaluate({k: v for k, v in row.items() if v != ""})
    row.update(expected_status=ev.status, max_eligible_amount=ev.max_eligible_amount or "", emi=ev.emi or "")
    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    r = random.Random(args.seed)
    rows = [gen_one(r, i + 1) for i in range(args.n)]
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    print(f"wrote {len(rows)} applicants -> {OUT}")
    print("status mix:", dict(Counter(r_["expected_status"] for r_ in rows)))
    print("loan mix:  ", dict(Counter(r_["loan_type"] for r_ in rows)))


if __name__ == "__main__":
    main()
