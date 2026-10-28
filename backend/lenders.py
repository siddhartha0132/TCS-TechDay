"""Multi-lender comparison over a SYNTHETIC lender panel (data/lenders.json).

Each lender's policy = the reference policy with that lender's product overrides
(rate, CIBIL cut-off, FOIR limit, caps). The same rules engine evaluates every
lender, so differences in the verdict come only from the published policy.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

from .rules import RULES, evaluate, fmt_inr, validate_profile

LENDERS_PATH = Path(__file__).resolve().parent.parent / "data" / "lenders.json"
LENDERS: list[dict[str, Any]] = json.loads(LENDERS_PATH.read_text(encoding="utf-8"))["lenders"]


def _policy_for(lender: dict[str, Any]) -> dict[str, Any]:
    policy = copy.deepcopy(RULES)
    for product, overrides in lender["products"].items():
        policy["products"][product].update(copy.deepcopy(overrides))
    return policy


POLICIES = {lender["id"]: _policy_for(lender) for lender in LENDERS}


def public_list() -> list[dict[str, Any]]:
    return [{"id": l["id"], "name": l["name"], "type": l["type"], "processing_fee_pct": l["processing_fee_pct"],
             "rates": {k: v["interest_rate"] for k, v in l["products"].items()}, "simulated": True} for l in LENDERS]


def lender_eligibility(lender_id: str, profile: dict[str, Any]) -> dict[str, Any]:
    lender = next((l for l in LENDERS if l["id"] == lender_id), None)
    if lender is None:
        raise KeyError(lender_id)
    ev = evaluate(profile, POLICIES[lender_id]).as_dict()
    clean, _ = validate_profile(profile)
    amount = ev.get("requested_amount") or 0
    fee = amount * lender["processing_fee_pct"] / 100
    n = round((ev.get("tenure_years") or 0) * 12)
    total_interest = (ev["emi"] * n - amount) if ev.get("emi") and n else None
    top_reason = next((c["detail"] for c in ev.get("checks", []) if c["hard"] and not c["passed"]), None)
    # Full amount available = eligible, or conditional only because of soft caveats (e.g. score near cut-off)
    full = ev["status"] == "ELIGIBLE" or (ev["status"] == "CONDITIONAL" and top_reason is None)
    return {
        "lender_id": lender["id"], "lender": lender["name"], "type": lender["type"], "simulated": True,
        "loan_type": clean.get("loan_type"), "status": ev["status"], "interest_rate": ev.get("interest_rate"),
        "emi": ev.get("emi"), "max_eligible_amount": ev.get("max_eligible_amount"), "requested_amount": amount or None,
        "processing_fee": round(fee) if amount else None, "processing_fee_pct": lender["processing_fee_pct"],
        "total_interest": round(total_interest) if total_interest and math.isfinite(total_interest) else None,
        "top_reason": top_reason, "summary": ev["summary"], "full_amount": full,
    }


def compare(profile: dict[str, Any]) -> dict[str, Any]:
    offers = [lender_eligibility(l["id"], profile) for l in LENDERS]
    # Full amount first, then a reduced amount, then not eligible
    tier = lambda o: 0 if o["full_amount"] else 1 if o["status"] == "CONDITIONAL" else 2  # noqa: E731
    # Full amount: cheapest rate first. Reduced amount: the most you can get first (then rate).
    offers.sort(key=lambda o: (tier(o), o["interest_rate"] or math.inf) if tier(o) == 0
                else (tier(o), -(o["max_eligible_amount"] or 0), o["interest_rate"] or math.inf))
    best = offers[0] if offers and tier(offers[0]) < 2 else None
    return {"simulated": True, "offers": offers, "best_lender_id": best["lender_id"] if best else None,
            "eligible_count": sum(o["full_amount"] for o in offers)}


def compare_text(result: dict[str, Any]) -> str:
    """Short chat-friendly comparison (English; translated upstream when needed)."""
    lines = ["Comparison across our simulated lender panel:"]
    for o in result["offers"]:
        mark = "✅" if o["full_amount"] else {"CONDITIONAL": "🟡", "NOT_ELIGIBLE": "🔴"}.get(o["status"], "•")
        if o["full_amount"]:
            lines.append(f"{mark} {o['lender']} — {o['interest_rate']}%, EMI {fmt_inr(o['emi'])}/month")
        elif o["status"] == "CONDITIONAL":
            lines.append(f"{mark} {o['lender']} — {o['interest_rate']}%, up to {fmt_inr(o['max_eligible_amount'], 'floor')}")
        else:
            why = (o["top_reason"] or "").replace(" vs. minimum", ", needs").replace(" vs. limit", ", limit").rstrip(".")
            lines.append(f"{mark} {o['lender']} — not eligible ({why})")
    best = next((o for o in result["offers"] if o["lender_id"] == result["best_lender_id"]), None)
    if best and best["full_amount"]:
        lines.append(f"Best option: {best['lender']} at {best['interest_rate']}%.")
    elif best:
        lines.append(f"Closest to your amount: {best['lender']}, up to {fmt_inr(best['max_eligible_amount'], 'floor')} at {best['interest_rate']}%.")
    return "\n".join(lines)
