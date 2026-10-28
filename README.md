# LoanMitra — Automated Loan Eligibility Chatbot

Single-agent GenAI chatbot for the TCS Technology Day problem statement *"Banking: Automated Loan Eligibility
Chatbot"*. An applicant types or speaks in **English, Hindi, Hinglish or 9 more Indian languages**; the agent collects
the facts, **shows them back for confirmation**, then an **auditable rules engine** decides. The reply gives the verdict,
reasons, EMI, a plan to become eligible, and a comparison across a (simulated) lender panel.

## Quick start

```bash
git clone https://github.com/siddhartha0132/TCS-TechDay.git && cd TCS-TechDay
uv venv --python 3.12 .venv                                    # or: python3.12 -m venv .venv
uv pip install --python .venv/bin/python -r requirements.txt   # exact, tested versions
cp .env.example .env                                           # every key is optional (see Configuration)
.venv/bin/uvicorn backend.main:app --port 8000
# http://localhost:8000      overview: problem, relevance, market gap, FAQ
# http://localhost:8000/chat the chatbot (Chat tab) and the eligibility form (Quick form tab)
```

Docker (single replica — read [docs/SCALING.md](docs/SCALING.md) before scaling out):

```bash
docker build -t loanmitra . && docker run -p 8000:8000 --env-file .env loanmitra
```

## How a check works

1. **PII masking** — PAN, Aadhaar, phone, email, card and account numbers are masked before anything else sees the text.
2. **Language** — English / Hindi / Hinglish handled natively; other Indian languages are translated to English and
   the reply translated back (Sarvam AI).
3. **Understanding** — an AI agent (or, with no AI available, a rule-based extractor) turns the message into facts and
   asks only for what's missing.
4. **Confirmation** — once everything is collected, the bot lists the exact values (with warnings such as
   "monthly income ₹6.5 L — is that per year?"). **No verdict is shown until the applicant confirms**; any later change
   asks again.
5. **Decision** — `backend/rules.py` evaluates `data/rules.json` (age, income, CIBIL, FOIR, LTV, tenure, income
   multiple). The AI explains; it never decides. Every reply carries an engine-authored verdict chip.
6. **Plan & compare** — improvement steps that are re-verified to actually help, what-if questions, and the same
   profile evaluated at four simulated lenders.

## Project layout

```
backend/
  main.py        FastAPI app and routes (below); serves frontend/
  agent.py       Session, AI tool loop over the provider chain, rule-based fallback agent, confirmation flow
  rules.py       Eligibility engine: validation, EMI, FOIR, LTV, age-at-maturity, caps, improvement plan
  lenders.py     Multi-lender comparison over data/lenders.json
  simulated.py   Simulated credit bureau + Account Aggregator services
  extractor.py   Rule-based fact extraction (EN / HI / Hinglish)
  numbers.py     Shared parsing of Indian amounts ("5 lacs", "12 LPA", "70 hazaar", "five lakh", Devanagari digits)
  privacy.py     PII masking (checksum + context aware)
  security.py    Rate limits, request-size limits, security headers / CSP
  store.py       Bounded in-memory session store with per-session locks
  voice.py       Sarvam AI speech-to-text, text-to-speech, translation
  audit.py       Decision audit log (no chat text or identifiers)
  i18n.py        Language detection and rule-mode reply templates
  documents.py   Document checklists
frontend/        landing.html (overview), chat.html + app.js (chat, quick form, dashboard)
data/            rules.json (policy), lenders.json (lender panel), test_cases.json, generate_synthetic.py
eval/run_eval.py Labelled evaluation (accuracy + latency) -> eval/REPORT.md
tests/           Attack / regression suite (pytest entry point: tests/test_suite.py)
docs/            ARCHITECTURE, SCALING, PRIVACY, DEMO_SCRIPT, PITCH
```

## API

| Route | Purpose |
|---|---|
| `POST /api/chat` | `{message, session_id?, language?}` → reply, profile, `pending_confirmation`, `review`, `evaluation`, `verified_verdict`, latency |
| `POST /api/reset` | Clear a session |
| `POST /api/evaluate` | `{applicant}` → rules-engine decision (direct integration; see note below) |
| `GET /api/lenders`, `POST /api/lenders/compare` | Lender panel; one applicant compared across lenders |
| `POST /api/sim/lenders/{id}/eligibility` | Simulated per-lender eligibility API |
| `POST /api/sim/bureau/soft-pull`, `POST /api/sim/aa/income` | Simulated bureau / Account Aggregator; require `consent: true` |
| `POST /api/stt`, `POST /api/tts` | Sarvam voice (only when `SARVAM_API_KEY` is set; the UI otherwise uses browser speech) |
| `GET /api/samples`, `GET /api/health` | Sample messages; status, active model, voice engine |

`/api/evaluate` and the lender endpoints decide on the profile exactly as supplied — they are meant for the quick form
(where the user typed every value) and system integrations. A production integration would add authentication.

## Configuration

Every key is optional; with none, the rules engine answers everything.

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | — / `claude-opus-5-5` | Claude, first in the chain when set |
| `ANTHROPIC_SERVER_FALLBACK` | `0` | `1` enables Anthropic's server-side refusal-fallback beta header (off by default) |
| `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` | — / `nvidia/nemotron-3.5-super-vl:free` | Free models via OpenRouter |
| `OPENROUTER_FALLBACK_MODELS` | `nvidia/nemotron-3.5-lightning:free,…` | Tried after NVIDIA |
| `NVIDIA_API_KEY` / `NVIDIA_MODEL` | — / `nvidia/nemotron-3-ultra-550b-a55b` | NVIDIA's API |
| `SARVAM_API_KEY` | — | Indian-language voice and translation |
| `LLM_TURN_BUDGET_S` | `13` | Hard per-reply budget; past it the rules engine answers |
| `RATE_CHAT_PER_MIN` / `RATE_VOICE_PER_MIN` / `RATE_API_PER_MIN` | 20 / 10 / 120 | Per-client rate limits (in-process) |
| `TRUST_PROXY` | `0` | `1` = take client IP from `X-Forwarded-For` (only behind your own proxy) |
| `ALLOWED_ORIGINS` | same-origin | Comma-separated origins allowed cross-site |
| `MAX_SESSIONS` / `SESSION_TTL_S` | 5000 / 3600 | In-memory session bounds |
| `AUDIT_LOG_PATH` | `logs/audit.jsonl` | Decision audit log |

**Provider chain:** Claude (if keyed) → OpenRouter free → NVIDIA → more OpenRouter free → rules engine. A provider is
skipped on rate limit, error or timeout. Calls run under a wall-clock deadline, so slow providers can't exceed the
budget; when the explanation can't fit, the engine renders it ("fast path"). Free tiers are rate-limited
(OpenRouter ≈ 50 requests/day without credits).

## Tests and what they do — and don't — show

```bash
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m pytest tests/test_suite.py -v      # or: .venv/bin/python tests/run_all.py
.venv/bin/python -m eval.run_eval --no-llm             # labelled eval, rules mode -> eval/REPORT.md
```

Measured on 28 Oct 2026, rules mode (no AI), on the repository's own data:

| Check | Result | Limitation |
|---|---|---|
| Invariant fuzzer, 20–30k random profiles (EMI/FOIR maths, monotonicity, every "up to X" and improvement tip re-verified) | 0 violations | Proves internal consistency, not that the policy is the right policy |
| 17 rule-boundary cases | 17/17 | Same author as the engine |
| 36 labelled multilingual conversations (verdict) | 36/36 | Small, same-author set; extractor was tuned on similar phrasing |
| 81 realistic extraction messages | 81/81 | Written by our red-team pass, not blind |
| PII masking, HTTP hardening, multi-turn probes | pass | — |

Not yet established: **accuracy on blind messages written by other people**, and a **measured GenAI-mode accuracy**
(live AI runs were spot checks, not a scored evaluation). `data/applicants.csv` labels come from the engine itself, so
it is demo data, not a validation set.

## Verdicts

- **ELIGIBLE** — every hard rule passes. **CONDITIONAL** — eligible for a smaller amount, or with a caveat
  (score near the cut-off, collateral, unknown score). **NOT_ELIGIBLE** — a hard rule fails; the reply says what to fix.
- An indicative *soft check*: no bureau enquiry, nothing stored. See [docs/PRIVACY.md](docs/PRIVACY.md).

## Lenders and simulated services

`data/lenders.json` holds four **fictional** lenders (public, private, small finance bank, NBFC) with illustrative
rates and cut-offs; each overrides the reference policy and the same engine decides. Ranking: full amount at the
lowest rate first, otherwise the largest amount. Simulated bureau and Account Aggregator responses are deterministic
per `mobile_last4`, flagged `"simulated": true`, and never touch real data.

## Front end

- `/` — immersive landing page: a Three.js (r160, MIT, served locally from `frontend/vendor/`) "ice vault" scene driven
  by scroll through five chapters (trust → profile → engine → live explanation from `/api/evaluate` → EMI planner).
  Respects `prefers-reduced-motion`, falls back to a static illustration without WebGL, pauses when off-screen.
  `/?ch=1..5` deep-links to a chapter.
- `/chat` — the assistant (chat + quick form), bank-statement upload (📎), lender comparison, voice.
- Bank statements: `POST /api/statement/analyze?consent=true` (PDF/CSV, ≤ 5 MB) — analysed in memory, aggregates only.
  `frontend/sample_statement.pdf` is a synthetic statement for demos (`python -m data.make_sample_statement`).
