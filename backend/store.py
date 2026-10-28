"""Bounded in-memory session store.

- Session IDs are 192-bit random tokens (unguessable; no cross-user access).
- LRU eviction caps memory at MAX_SESSIONS; idle sessions expire after SESSION_TTL_S.
- A per-session lock serialises turns so two concurrent requests can't interleave
  tool_use / tool_result blocks in the same conversation history.

Nothing is persisted. For horizontal scaling, replace this with a Redis-backed
store (profile + history serialised as JSON) and keep the same interface.
"""
from __future__ import annotations

import os
import secrets
import threading
import time
from collections import OrderedDict
from typing import Optional

from .agent import Session

MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "5000"))
SESSION_TTL_S = int(os.getenv("SESSION_TTL_S", "3600"))


class SessionStore:
    def __init__(self) -> None:
        self._sessions: OrderedDict[str, Session] = OrderedDict()
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def _expire(self, now: float) -> None:
        while self._sessions:
            sid, s = next(iter(self._sessions.items()))
            if now - s.updated <= SESSION_TTL_S and len(self._sessions) <= MAX_SESSIONS:
                break
            self._sessions.popitem(last=False)
            self._locks.pop(sid, None)

    def get_or_create(self, session_id: Optional[str]) -> tuple[Session, threading.Lock]:
        now = time.time()
        with self._guard:
            s = self._sessions.get(session_id or "")
            if s is None or now - s.updated > SESSION_TTL_S:
                s = Session(id=secrets.token_urlsafe(24))
                self._sessions[s.id] = s
                self._locks[s.id] = threading.Lock()
            s.updated = now
            self._sessions.move_to_end(s.id)
            self._expire(now)
            return s, self._locks[s.id]

    def get(self, session_id: str) -> Optional[Session]:
        with self._guard:
            return self._sessions.get(session_id)

    def __len__(self) -> int:
        return len(self._sessions)

    def stats(self) -> dict:
        with self._guard:
            return {"active": len(self._sessions), "max_sessions": MAX_SESSIONS, "ttl_s": SESSION_TTL_S}


sessions = SessionStore()
