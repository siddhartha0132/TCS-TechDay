"""SIMULATED external services used for eligibility checking.

Stand-ins for the integrations a real deployment would call. Deterministic: the
same seed (last 4 digits of a mobile number) always returns the same synthetic
data, so demos are repeatable. Nothing real is looked up and nothing is stored.

- Credit bureau soft pull   -> score, active loans, recent enquiries
- Account Aggregator (AA)   -> 6 months of salary credits and EMI debits
"""
from __future__ import annotations

import hashlib
import random
import time
from typing import Any

DISCLAIMER = "Simulated response for demonstration. No real bureau or bank data was accessed."


def _rng(kind: str, seed: str) -> random.Random:
    return random.Random(int(hashlib.sha256(f"{kind}:{seed}".encode()).hexdigest()[:12], 16))


def bureau_soft_pull(seed: str) -> dict[str, Any]:
    r = _rng("bureau", seed)
    score = int(min(880, max(580, r.gauss(735, 55))))
    loans = []
    for _ in range(r.choice([0, 0, 1, 1, 2])):
        kind = r.choice(["Credit card", "Car loan", "Personal loan", "Two-wheeler loan", "Consumer durable"])
        loans.append({"type": kind, "monthly_emi": r.choice([2500, 4000, 6500, 9000, 12000, 18000]),
                      "status": "Current", "dpd_last_12m": r.choice([0, 0, 0, 0, 30])})
    return {
        "simulated": True, "provider": "Simulated credit bureau", "pull_type": "soft (no score impact)",
        "report_id": f"SIM-CB-{_rng('id', seed).randrange(10**8):08d}", "fetched_at": int(time.time()),
        "credit_score": score, "active_loans": loans, "total_monthly_emi": sum(l["monthly_emi"] for l in loans),
        "enquiries_last_6m": r.choice([0, 1, 1, 2, 3, 5]), "disclaimer": DISCLAIMER,
    }


def aa_income(seed: str) -> dict[str, Any]:
    r = _rng("aa", seed)
    salaried = r.random() < 0.72
    base = int(round(r.lognormvariate(11.0, 0.45) / 1000) * 1000)
    months = []
    for i in range(6):
        credit = base if salaried else int(base * r.uniform(0.7, 1.35))
        months.append({"month_offset": -i, "income_credits": credit})
    avg = round(sum(m["income_credits"] for m in months) / 6, -2)
    # EMI debits seen in the statement mirror the bureau's active loans for the same person
    emi = bureau_soft_pull(seed)["total_monthly_emi"]
    return {
        "simulated": True, "provider": "Simulated Account Aggregator", "consent_id": f"SIM-AA-{_rng('c', seed).randrange(10**8):08d}",
        "period_months": 6, "employment_type": "salaried" if salaried else "self_employed",
        "avg_monthly_income": avg, "monthly": months, "avg_monthly_emi_debits": emi,
        "bounced_emis_6m": r.choice([0, 0, 0, 1]), "disclaimer": DISCLAIMER,
    }
