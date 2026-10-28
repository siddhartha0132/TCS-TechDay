"""Per-model evaluation: runs the labelled conversations through ONE backend at a time (no fallback chain).

    .venv/bin/python -m eval.model_eval --config deterministic            # all 36 cases, no AI
    .venv/bin/python -m eval.model_eval --config nvidia --cases all
    .venv/bin/python -m eval.model_eval --config openrouter --cases subset # 12-case stratified subset (free-tier quota)

Appends results to eval/model_results.json (one entry per config), which eval/make_report_pdf.py turns into the PDF.
Measured per case: final verdict vs label, extraction accuracy (after the first message and at the end), turns,
per-turn latency, how each reply was produced (model / engine fast path / rule-based fallback), reply language,
and every raw model call (latency, success, error).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from backend import agent  # noqa: E402
from eval.run_eval import CASES, answer_for, close  # noqa: E402

RESULTS = ROOT / "eval" / "model_results.json"
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
CALLS: list[dict] = []


def _subset() -> list[dict]:
    """12 cases: every Hindi and Hinglish case, plus English cases covering each verdict and loan type."""
    nl = CASES["nl_cases"]
    picked = [c for c in nl if c["lang"] != "en"]
    seen: set = set()
    for c in nl:
        key = (c["expected_status"], c["expected_fields"].get("loan_type"))
        if c["lang"] == "en" and key not in seen and len(picked) < 12:
            seen.add(key)
            picked.append(c)
    return picked


def _instrument() -> None:
    """Record every raw model call: which model, how long, whether it succeeded, whether it beat the deadline."""
    for name in ("_call_anthropic", "_call_nvidia"):
        original = getattr(agent.GenAIAgent, name)

        def wrapped(self, b, history, timeout, _orig=original):
            started = time.perf_counter()
            try:
                out = _orig(self, b, history, timeout)
                CALLS.append({"model": b.model, "s": time.perf_counter() - started, "ok": True, "in_time": time.perf_counter() - started <= timeout})
                return out
            except Exception as exc:
                CALLS.append({"model": b.model, "s": time.perf_counter() - started, "ok": False, "error": str(exc)[:80]})
                raise
        setattr(agent.GenAIAgent, name, wrapped)


def _configure(config: str) -> str:
    if config == "deterministic":
        for key in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "NVIDIA_API_KEY"):
            os.environ[key] = ""
        return "Rule-based agent (no AI)"
    os.environ["ANTHROPIC_API_KEY"] = ""  # never fall through to a paid model during evaluation
    g = agent.GenAIAgent()
    if config == "nvidia":
        g.chain = [agent.Backend("nvidia", os.getenv("NVIDIA_MODEL", agent.NVIDIA_DEFAULT))]
    elif config == "openrouter":
        g.chain = [agent.Backend("openrouter", agent._openrouter_id(os.getenv("OPENROUTER_MODEL", agent.OPENROUTER_FREE_DEFAULT)))]
    else:
        raise SystemExit(f"unknown config {config}")
    agent._genai = g
    _instrument()
    return g.chain[0].model


def _field_score(profile: dict, expected: dict) -> tuple[int, int]:
    return sum(1 for k, v in expected.items() if k in profile and close(profile[k], v)), len(expected)


def _language_ok(lang: str, reply: str) -> bool:
    has_dev = bool(DEVANAGARI.search(reply))
    return has_dev if lang == "hi" else not has_dev


def run_case(c: dict) -> dict:
    s = agent.Session()
    facts = c["expected_fields"]
    turns: list[dict] = []

    def turn(text: str) -> dict:
        before = len(CALLS)
        r = agent.handle_message(s, text)
        turns.append({"latency_ms": r["latency_ms"], "source": r["reply_source"], "mode": r["mode"], "model": r["model"],
                      "calls": len(CALLS) - before, "lang_ok": _language_ok(c["lang"], r["reply"])})
        return r

    r = turn(c["text"])
    first_ok, first_total = _field_score(r["profile"], facts)
    while r["evaluation"] is None and len(turns) < 8:
        if r.get("pending_confirmation"):
            r = turn("Yes, confirm")
            continue
        answers = [a for a in (answer_for(f, facts) for f in (r["missing_fields"] or ["loan_type"])[:3]) if a]
        if not answers:
            break
        r = turn(" ".join(answers))
    got = r["evaluation"]["status"] if r["evaluation"] else "INCOMPLETE"
    end_ok, end_total = _field_score(r["profile"], facts)
    return {"id": c["id"], "lang": c["lang"], "loan_type": facts.get("loan_type"), "expected": c["expected_status"], "got": got,
            "correct": got == c["expected_status"], "first_fields": [first_ok, first_total], "final_fields": [end_ok, end_total],
            "turns": turns}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, choices=["deterministic", "nvidia", "openrouter"])
    ap.add_argument("--cases", default="all", choices=["all", "subset"])
    args = ap.parse_args()
    label = _configure(args.config)
    cases = CASES["nl_cases"] if args.cases == "all" else _subset()
    started = time.time()
    results = []
    for i, c in enumerate(cases, 1):
        results.append(run_case(c))
        last = results[-1]
        print(f"[{i}/{len(cases)}] {c['id']} {c['lang']} expected={last['expected']} got={last['got']} "
              f"{'OK' if last['correct'] else 'MISS'} turns={len(last['turns'])} max_ms={max(t['latency_ms'] for t in last['turns'])}", flush=True)
    data = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}
    data[f"{args.config}:{args.cases}"] = {"config": args.config, "model": label, "cases": args.cases, "ran_at": time.strftime("%Y-%m-%d %H:%M"),
                                           "budget_s": agent.TURN_BUDGET_S, "wall_s": round(time.time() - started), "results": results, "calls": CALLS}
    RESULTS.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    ok = sum(r["correct"] for r in results)
    print(f"{label}: verdict {ok}/{len(results)} -> {RESULTS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
