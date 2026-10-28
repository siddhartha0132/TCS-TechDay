"""pytest entry point: each attack/regression suite runs as one test, in its own process.

    .venv/bin/python -m pytest tests/test_suite.py -v
Never calls a paid API (tests/_setup.py blanks every provider key).
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SUITES = {
    "rules_invariant_fuzzer": ["tests/fuzz_rules.py", "20000", "11"],
    "edge_values": ["tests/probe_edges.py"],
    "extractor_messages": ["tests/probe_extractor.py"],
    "pii_masking": ["tests/probe_privacy.py"],
    "http_hardening": ["tests/probe_http.py"],
    "multi_turn_conversations": ["tests/probe_agent.py"],
    "labelled_eval_rules_mode": ["-m", "eval.run_eval", "--no-llm"],
}


@pytest.mark.parametrize("name", list(SUITES))
def test_suite(name: str) -> None:
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    for key in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "NVIDIA_API_KEY", "SARVAM_API_KEY"):
        env[key] = ""
    r = subprocess.run([sys.executable, *SUITES[name]], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", env=env)
    out = r.stdout + r.stderr
    assert r.returncode == 0 and "Traceback" not in out, out[-3000:]
