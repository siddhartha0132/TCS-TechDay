"""Append-only decision audit trail (JSON Lines) that never contains raw chat text or identifiers.

One line per decision event: when, which (hashed) session, which loan type, the verdict, the exact
policy version that produced it, and how it was produced. Enough to answer "why did the bot say
that, under which rules?" without storing anything a customer typed.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIT_PATH = Path(os.getenv("AUDIT_LOG_PATH", str(ROOT / "logs" / "audit.jsonl")))
_lock = threading.Lock()
log = logging.getLogger("loanmitra.audit")


def _policy_version() -> str:
    h = hashlib.sha256()
    for name in ("rules.json", "lenders.json"):
        h.update((ROOT / "data" / name).read_bytes())
    return h.hexdigest()[:12]


POLICY_VERSION = _policy_version()


def record(event: str, session_id: str, **fields) -> None:
    """Never raises: auditing must not break a customer reply."""
    entry = {"ts": round(time.time(), 3), "event": event, "policy_version": POLICY_VERSION,
             "session": hashlib.sha256(session_id.encode()).hexdigest()[:16], **fields}
    try:
        with _lock:
            AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
            with AUDIT_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        log.warning("audit log not writable at %s", AUDIT_PATH)
