# Scaling and deployment

## What the demo build is

A **single-replica** service: one container, one uvicorn worker. Two pieces of state live in that process:

| State | Where | Bound |
|---|---|---|
| Chat sessions (profile, history, confirmation) | `backend/store.py`, in memory | `MAX_SESSIONS` (5,000, LRU) and `SESSION_TTL_S` (1 h) |
| Rate-limit buckets | `backend/security.py`, in memory | 50,000 client keys (LRU) |

Consequences, by design for the demo:

- A restart clears all sessions (nothing is persisted, which is also the privacy posture).
- Running **more than one worker or replica breaks sessions** (a user's next message may land on a process that
  doesn't know them) and **weakens rate limits** (each replica counts separately). That's why the Dockerfile pins
  `--workers 1`.

## Going to N replicas

1. **Sessions → shared store.** Serialise `Session` (profile, confirmation signature, LLM history) to Redis with the
   same TTL, keyed by the session token; keep the per-session lock as a Redis lock (`SET NX PX`). The `SessionStore`
   interface (`get_or_create`, `get`) is the only thing that changes.
   *Stop-gap:* sticky sessions at the load balancer (cookie affinity) — works, but a replica restart still drops its users.
2. **Rate limits → the edge.** Enforce per-client limits at the API gateway / CDN (e.g. Cloudflare, API Gateway), or
   swap `TokenBucketLimiter` for a Redis token bucket with the same `allow(key, per_minute)` signature. Set
   `TRUST_PROXY=1` only behind a proxy you control, so `X-Forwarded-For` can't be spoofed.
3. **Workers.** The rules engine is pure CPU and fast (thousands of evaluations/s/core); model calls are I/O-bound
   on a thread pool. Once state is shared, run `WEB_CONCURRENCY` ≈ 2 × cores per replica.
4. **Audit log.** `logs/audit.jsonl` is per container. In production, mount a volume or ship the lines to a log
   pipeline (it never contains chat text or identifiers — see `PRIVACY.md`).

## Failure behaviour

| Failure | What the user sees |
|---|---|
| All AI providers slow / rate-limited / down | Rules engine answers within the 13 s budget (`LLM_TURN_BUDGET_S`); badge shows "Rules engine (AI busy)" |
| Sarvam (voice / translation) down | Browser speech is used; regional-language replies fall back to English |
| Process restart | Sessions are lost; the user starts a new check (no data to recover, by design) |
| Client exceeds rate limit | HTTP 429 with `Retry-After`; the UI shows a friendly message |

## Capacity notes

- Each chat turn uses 0–2 model calls (0 in rules mode or when the applicant confirms; the confirmation card and
  fast path are rendered by the engine). Free model tiers are rate-limited (OpenRouter free ≈ 50 requests/day without
  credits) — for real traffic, use a paid key or a self-hosted model behind the same provider chain.
- The policy (`data/rules.json`, `data/lenders.json`) is loaded at start-up; changing it means a rolling restart.
  Every audit line records the `policy_version` hash, so decisions stay traceable across policy changes.
