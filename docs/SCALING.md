# Scaling LoanMitra

Current posture: a **single container, single worker** (`Dockerfile`: `--workers 1`).
That is deliberate — sessions and rate limits are in-process — and it is fine
for a demo. This doc is the path to production. Steps are ordered; each one is
independently shippable.

## 0. What already exists

- **LLM guards** (`backend/agent.py`): process-wide concurrency semaphore
  (`LLM_MAX_CONCURRENCY`, default 8), per-backend circuit breaker
  (`LLM_CB_THRESHOLD`/`LLM_CB_COOLDOWN_S`), per-session call cap
  (`LLM_MAX_CALLS_PER_SESSION`, overflow degrades to the rules agent), and
  counters exposed at `GET /api/health` → `llm`.
- **Probes**: `GET /livez` (process up, no dependencies) and `GET /readyz`
  (policy loaded, session store stats). Point Kubernetes liveness/readiness
  here, not at `/api/health`.
- **Bounded memory**: sessions LRU-capped (`MAX_SESSIONS`, default 5000, 1 h TTL);
  rate limiter LRU-capped at 50k client keys.
- **Voice STT** runs off the event loop (`asyncio.to_thread`), so one slow
  transcription can't stall the loop. `/api/chat` and `/api/evaluate` are sync
  endpoints, which FastAPI already runs in its threadpool.

## 1. Redis-backed sessions (unlocks everything else)

Replace `backend/store.py` with the same interface over Redis:

- Key `loanmitra:session:<id>` → JSON `{profile, history, transcript tail,
  lang, expected_field, llm_calls, updated}`. `SET ... EX 3600` refreshes TTL
  on every turn (replaces `_expire`).
- Per-session lock → Redlock/Redisson-style short lock (`SET NX PX 15000` +
  release Lua script) around `handle_message`, same as today's
  non-blocking `409` behaviour.
- Keep `SessionStore` as the local fallback when `REDIS_URL` is unset, so the
  laptop demo still runs with zero dependencies.
- New dependency: `redis>=5` (sync client is fine; session I/O stays in the
  threadpool with the sync endpoints).

## 2. Redis rate limiting

`backend/security.py:TokenBucketLimiter` is per-process, so N replicas multiply
every limit by N. Swap the internals for a sliding window:

- `INCR loanmitra:rl:<group>:<client>:<minute>` + `EXPIRE 70` per request;
  allow while count ≤ limit. One round-trip, no Lua needed.
- Alternative: terminate rate limiting at the edge (Cloudflare / API gateway /
  ingress annotations) and keep the in-process limiter as defence in depth.
- Make `max_keys` env-tunable either way (`RATE_LIMIT_MAX_KEYS`).

## 3. Replicas

1. Set `Dockerfile`/`CMD` to `--workers 2` (or `$WEB_CONCURRENCY`) once
   sessions are in Redis.
2. Run N pods behind a Service; sessions no longer need stickiness, but keep
   `backend.sessions` affinity off and verify with two replicas + the eval
   harness before wider rollout.
3. Interim (no Redis yet): exactly one replica, or sticky sessions at ingress
   (`nginx.ingress.kubernetes.io/affinity: cookie`).

## 4. Split static traffic

`main.py` serves `/static`, `/` and `/chat` from the API process. In
production, put `frontend/` on a CDN or object storage + CDN and keep the
FastAPI deployment API-only (smaller pods, no `no-store` on immutable assets).
The CSP already allows `style-src 'self' https://fonts.googleapis.com` —
extend `script-src`/`style-src` to the CDN origin when you split.

## 5. Observe, then autoscale

- Export Prometheus metrics (new dep `prometheus-client`): per-endpoint
  latency histogram (chat turns, model calls), `/api/evaluate` QPS, limiter
  rejects (429 rate), breaker state, semaphore saturation, session count.
  The `LLM_STATS` counters in `/api/health` are the seed set — scrape or log
  them until real metrics land.
- HPA on chat p95 (custom metric) with a floor of 2 replicas; alert on
  `budget_exceeded` growth (cost) and breaker-open rate (provider outage).
- Load test before launch day: k6 or Locust script hitting `/api/chat`
  (multi-turn, mixed languages) and `/api/evaluate` (simulator sliders);
  assert p95 < 15 s for chat and p99 < 200 ms for evaluate at the expected
  jury-room concurrency (start with 50 VUs).

## 6. Environment knobs (scaling-relevant)

| Variable | Default | Meaning |
|---|---|---|
| `MAX_SESSIONS` / `SESSION_TTL_S` | 5000 / 3600 | Session memory bound + idle expiry |
| `RATE_*_PER_MIN` | 20 / 10 / 120 | Chat / voice / other API limits |
| `LLM_TURN_BUDGET_S` | 13 | Hard per-turn model budget |
| `LLM_MAX_CONCURRENCY` | 8 | Provider calls in flight, per process |
| `LLM_CB_THRESHOLD` / `LLM_CB_COOLDOWN_S` | 3 / 60 | Circuit breaker trips + rest time |
| `LLM_MAX_CALLS_PER_SESSION` | 30 | Cost bound; overflow uses the rules agent |
| `REDIS_URL` | — | Enables Redis sessions + limiter (step 1–2) |
| `TRUST_PROXY` | 0 | Set `1` behind ingress so rate limits see real client IPs |
| `ALLOWED_ORIGINS` | same-origin | Partner origins for cross-site calls |

## 7. What NOT to scale yet

The rules engine is pure Python and already does thousands of evals/sec —
profile before touching it. The LLM chain is sequential by design (fallback,
not fan-out); do not parallelise providers — it multiplies cost without
improving the p50 the jury sees.
