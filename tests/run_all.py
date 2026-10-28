"""Run the whole attack/regression suite. Never calls a paid API.

    .venv/bin/python tests/run_all.py
"""
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
SUITE = [
    ("rules invariant fuzzer (30k profiles)", [PY, "tests/fuzz_rules.py", "30000", "11"]),
    ("edge values (NaN/inf/0/negative/garbage)", [PY, "tests/probe_edges.py"]),
    ("extractor (81 realistic messages)", [PY, "tests/probe_extractor.py"]),
    ("PII masking", [PY, "tests/probe_privacy.py"]),
    ("HTTP hardening", [PY, "tests/probe_http.py"]),
    ("multi-turn conversations", [PY, "tests/probe_agent.py"]),
    ("list answers (bare values, one per line)", [PY, "tests/probe_list_answers.py"]),
    ("labelled eval (deterministic)", [PY, "-m", "eval.run_eval", "--no-llm"]),
]

if __name__ != "__main__":
    raise ImportError("run directly, or use pytest tests/test_suite.py")

failed = 0
for name, cmd in SUITE:
    t = time.perf_counter()
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                       env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    ok = r.returncode == 0 and "Traceback" not in r.stdout + r.stderr
    failed += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {name:45s} {time.perf_counter() - t:5.1f}s")
    if not ok:
        print((r.stdout + r.stderr)[-1500:])
print(f"\n{len(SUITE) - failed}/{len(SUITE)} suites passed")
sys.exit(1 if failed else 0)
