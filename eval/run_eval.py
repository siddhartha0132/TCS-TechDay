"""Evaluation harness: rules consistency, NL extraction, end-to-end conversation accuracy, latency.

Usage:  python -m eval.run_eval            # uses GenAI mode if ANTHROPIC_API_KEY is set, else deterministic
        python -m eval.run_eval --no-llm   # force deterministic mode
Writes eval/REPORT.md.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import agent  # noqa: E402
from backend.extractor import extract  # noqa: E402
from backend.rules import REQUIRED_FIELDS, evaluate  # noqa: E402

CASES = json.loads((ROOT / "data" / "test_cases.json").read_text(encoding="utf-8"))
REPORT = ROOT / "eval" / "REPORT.md"


def close(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= max(1.0, 0.01 * abs(b))
    return str(a).lower() == str(b).lower()


# Natural-language answers the "applicant" gives when the bot asks for a missing field.
def answer_for(field: str, facts: dict) -> str | None:
    v = facts.get(field)
    if v is None:
        return None
    n = float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0
    return {
        "loan_type": lambda: f"It's a {v} loan.",
        "loan_amount": lambda: f"I need a loan amount of {n:,.0f} rupees.",
        "tenure_years": lambda: f"Tenure {n:g} years.",
        "age": lambda: f"I am {n:g} years old.",
        "monthly_income": lambda: f"My net salary is {n:,.0f} per month.",
        "employment_type": lambda: "I am salaried." if v == "salaried" else "I am self-employed.",
        "credit_score": lambda: f"My credit score is {n:g}.",
        "existing_emi": lambda: f"I pay {n:,.0f} EMI currently." if n else "I have no existing EMIs.",
        "property_value": lambda: f"The property is worth {n:,.0f}.",
        "vehicle_price": lambda: f"The car's on-road price is {n:,.0f}.",
        "study_abroad": lambda: "The course is abroad." if v else "The course is in India.",
        "co_applicant_income": lambda: f"My father's income is {n:,.0f} per month.",
        "co_applicant_credit_score": lambda: f"My father's credit score is {n:g}.",
        "co_applicant_existing_emi": lambda: f"My father pays {n:,.0f} EMI." if n else "My father has no EMIs.",
    }[field]()


def run() -> str:
    mode = "genai" if agent.genai_available() else "deterministic"
    lines = [f"# Evaluation report", "", f"- Mode: **{mode}**" + (f" (model `{agent.MODEL}`, effort `{agent.EFFORT}`)" if mode == "genai" else ""),
             f"- Generated: {time.strftime('%Y-%m-%d %H:%M')}", ""]

    # ---------------- A. rules engine consistency
    st = CASES["structured_cases"]
    st_ok = 0
    st_rows = []
    for c in st:
        got = evaluate(c["applicant"]).status
        ok = got == c["expected_status"]
        st_ok += ok
        st_rows.append(f"| {c['id']} | {c['note']} | {c['expected_status']} | {got} | {'✅' if ok else '❌'} |")
    lines += [f"## A. Rules engine — {st_ok}/{len(st)} = **{100 * st_ok / len(st):.0f}%**", "",
              "| id | case | expected | got | ok |", "|---|---|---|---|---|", *st_rows, ""]

    # ---------------- B. single-shot NL extraction (regex baseline, no LLM)
    nl = CASES["nl_cases"]
    field_total = field_ok = 0
    b_status_ok = 0
    b_rows = []
    for c in nl:
        got = extract(c["text"])
        exp = c["expected_fields"]
        misses = []
        for k, v in exp.items():
            field_total += 1
            if k in got and close(got[k], v):
                field_ok += 1
            else:
                misses.append(f"{k}: got {got.get(k)!r}, want {v!r}")
        extras = [k for k in got if k not in exp]
        got_status = evaluate(got).status if got.get("loan_type") else "INCOMPLETE"
        ok = got_status == c["expected_status"]
        b_status_ok += ok
        b_rows.append(f"| {c['id']} | {c['lang']} | {c['expected_status']} | {got_status} | {'✅' if ok else '❌'} | {'; '.join(misses + [f'extra {e}' for e in extras]) or '—'} |")
    lines += [f"## B. Regex extraction baseline (single message) — fields {field_ok}/{field_total} = **{100 * field_ok / field_total:.0f}%**, "
              f"verdict {b_status_ok}/{len(nl)} = **{100 * b_status_ok / len(nl):.0f}%**", "",
              "| id | lang | expected | got | ok | field mismatches |", "|---|---|---|---|---|---|", *b_rows, ""]

    # ---------------- C. end-to-end conversation through the agent (LLM if available)
    c_ok = 0
    fallbacks = 0  # replies where the LLM errored and the deterministic brain answered
    latencies: list[int] = []
    turns_list: list[int] = []
    c_rows = []
    pii_ok = True
    for c in nl:
        s = agent.Session()
        facts = c["expected_fields"]
        r = agent.handle_message(s, c["text"])
        latencies.append(r["latency_ms"])
        fallbacks += "error" in r["mode"]
        if c.get("expect_pii") and not set(c["expect_pii"]) <= set(r["pii_masked"]):
            pii_ok = False
        turns = 1
        # Keep answering what the bot asks for, from the labelled facts, up to 8 turns
        while r["evaluation"] is None and turns < 8:
            if r.get("pending_confirmation"):
                r = agent.handle_message(s, "Yes, confirm")
                latencies.append(r["latency_ms"])
                turns += 1
                continue
            missing = r["missing_fields"] or ["loan_type"]
            answers = [a for a in (answer_for(f, facts) for f in missing[:3]) if a]
            if not answers:
                break  # the applicant genuinely doesn't know (e.g. nl34) -> stays INCOMPLETE
            r = agent.handle_message(s, " ".join(answers))
            latencies.append(r["latency_ms"])
            fallbacks += "error" in r["mode"]
            turns += 1
        got_status = r["evaluation"]["status"] if r["evaluation"] else "INCOMPLETE"
        ok = got_status == c["expected_status"]
        c_ok += ok
        turns_list.append(turns)
        c_rows.append(f"| {c['id']} | {c['lang']} | {c['expected_status']} | {got_status} | {'✅' if ok else '❌'} | {turns} | {max(latencies[-turns:])} |")

    p50 = statistics.median(latencies)
    p95 = sorted(latencies)[int(0.95 * (len(latencies) - 1))]
    under = sum(1 for l in latencies if l < 15000)
    lines += [f"## C. End-to-end conversation ({mode}) — verdict {c_ok}/{len(nl)} = **{100 * c_ok / len(nl):.0f}%**", "",
              f"- Replies under 15 s: **{under}/{len(latencies)}** ({100 * under / len(latencies):.0f}%) · latency p50 {p50:.0f} ms · p95 {p95} ms · max {max(latencies)} ms",
              f"- Average turns to verdict: {statistics.mean(turns_list):.1f}",
              f"- Replies where the LLM failed and the deterministic fallback answered: **{fallbacks}/{len(latencies)}**"
              + (" ⚠️ section C does not reflect GenAI accuracy" if fallbacks else ""),
              f"- PII masking on labelled cases: {'✅' if pii_ok else '❌'}", "",
              "| id | lang | expected | got | ok | turns | max ms |", "|---|---|---|---|---|---|---|", *c_rows, ""]

    lines += ["## How to read this", "",
              "- **A** proves the policy engine matches the hand-written expectations at rule boundaries (score cut-offs, FOIR, LTV, age at maturity).",
              "- **B** is the no-LLM regex baseline on a single free-text message — this is what powers the demo without an API key.",
              "- **C** is the metric that matters for the problem statement: the agent collects what it needs across turns and the final verdict is compared with the label. "
              "With `ANTHROPIC_API_KEY` set, section C exercises Claude's understanding of English / Hindi / Hinglish input.",
              "- Verdict categories: ELIGIBLE, CONDITIONAL (eligible for a smaller amount or with a caveat), NOT_ELIGIBLE, INCOMPLETE."]
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true", help="force deterministic mode")
    args = ap.parse_args()
    if args.no_llm:
        for key in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "NVIDIA_API_KEY"):
            os.environ[key] = ""  # empty (not popped) so load_dotenv() can't refill it
    report = run()
    REPORT.write_text(report, encoding="utf-8")
    print(report)
    print(f"\n-> written to {REPORT}")
