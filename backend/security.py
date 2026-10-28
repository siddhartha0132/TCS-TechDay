"""HTTP hardening: rate limiting, request-size limits, security headers, client identity.

All limits are configurable through environment variables so the same build
runs a hackathon laptop demo and a multi-replica deployment.
"""
from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

TRUST_PROXY = os.getenv("TRUST_PROXY", "0") == "1"

# requests per minute, per client, per route group
RATE_LIMITS = {
    "chat": int(os.getenv("RATE_CHAT_PER_MIN", "20")),
    "voice": int(os.getenv("RATE_VOICE_PER_MIN", "10")),
    "api": int(os.getenv("RATE_API_PER_MIN", "120")),
}
ROUTE_GROUPS = {"/api/chat": "chat", "/api/stt": "voice", "/api/tts": "voice"}

MAX_BODY_BYTES = {"/api/stt": 5 * 1024 * 1024}  # one short voice note
DEFAULT_MAX_BODY = 64 * 1024

CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' https://fonts.googleapis.com",
    "font-src https://fonts.gstatic.com",
    "img-src 'self' data:",
    "media-src 'self' data: blob:",
    "connect-src 'self'",
    "frame-ancestors 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "object-src 'none'",
])
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "microphone=(self), camera=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cache-Control": "no-store",
}


def client_id(request: Request) -> str:
    if TRUST_PROXY:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class TokenBucketLimiter:
    """In-process sliding token bucket. Bounded memory (LRU of client keys).

    For multi-replica deployments put the limit at the edge (Cloudflare / API
    gateway) or swap this for a Redis-backed limiter with the same interface.
    """

    def __init__(self, max_keys: int = 50_000) -> None:
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()
        self._lock = threading.Lock()
        self._max_keys = max_keys

    def allow(self, key: str, per_minute: int) -> tuple[bool, float]:
        rate = per_minute / 60.0
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.pop(key, (float(per_minute), now))
            tokens = min(float(per_minute), tokens + (now - last) * rate)
            allowed = tokens >= 1.0
            if allowed:
                tokens -= 1.0
            self._buckets[key] = (tokens, now)
            while len(self._buckets) > self._max_keys:
                self._buckets.popitem(last=False)
        retry_after = 0.0 if allowed else (1.0 - tokens) / rate
        return allowed, retry_after


limiter = TokenBucketLimiter()


class SecurityMiddleware(BaseHTTPMiddleware):
    """Rate limit /api/*, reject oversized declared bodies early, add security headers."""

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if path.startswith("/api/"):
            group = ROUTE_GROUPS.get(path, "api")
            ok, retry = limiter.allow(f"{group}:{client_id(request)}", RATE_LIMITS[group])
            if not ok:
                return self._headers(JSONResponse({"detail": "Too many requests, please slow down."}, status_code=429,
                                                  headers={"Retry-After": str(int(retry) + 1)}))
            if request.method in ("POST", "PUT", "PATCH"):
                # Require a declared length: the HTTP server enforces body == Content-Length,
                # so checking the header bounds memory before a single byte is buffered.
                declared = request.headers.get("content-length", "")
                if not declared.isdigit():
                    return self._headers(JSONResponse({"detail": "Content-Length required."}, status_code=411))
                if int(declared) > MAX_BODY_BYTES.get(path, DEFAULT_MAX_BODY):
                    return self._headers(JSONResponse({"detail": "Request body too large."}, status_code=413))
        return self._headers(await call_next(request))

    @staticmethod
    def _headers(resp: Response) -> Response:
        for k, v in SECURITY_HEADERS.items():
            resp.headers.setdefault(k, v)
        return resp
