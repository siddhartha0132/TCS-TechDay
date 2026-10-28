# LoanMitra — Automated Loan Eligibility Chatbot

Single-agent GenAI chatbot that talks to a loan applicant in **English, Hindi or Hinglish** (text or voice),
collects the facts it needs, runs them through an **auditable rules engine**, and replies with an instant verdict,
the reasons, the EMI, and concrete *what-you-can-do-next* steps — in well under 15 seconds.

Built for the TCS Technology Day problem statement *"Banking: Automated Loan Eligibility Chatbot"*.

## Why this design

| Problem statement asks for | How LoanMitra does it |
|---|---|
| Single-agent chatbot | One Claude agent with three tools (`update_applicant_profile`, `what_if`, `list_required_documents`) |
| Evaluates input against eligibility rules | Deterministic engine in [backend/rules.py](backend/rules.py), policy in [data/rules.json](data/rules.json) — the LLM never decides eligibility |
| Personalised feedback + next steps | Counterfactuals computed from the rules: max eligible amount, tenure that would work, EMIs to close, score points needed, co-applicant income needed |
| 80%+ accuracy | Labelled test set + eval harness ([eval/run_eval.py](eval/run_eval.py)); current run: 100% on rules, extraction and end-to-end verdicts |
| < 15 s response | Latency measured per reply and shown in the UI; `effort=low` on the model keeps GenAI replies fast |
| Synthetic data, privacy | 300 generated applicants ([data/generate_synthetic.py](data/generate_synthetic.py)); PAN / Aadhaar / phone / email masked before any processing; sessions in memory only |
| Chat UI, docs, demo | [frontend/](frontend/), [docs/](docs/) |

**Works with or without an API key.** Without `ANTHROPIC_API_KEY` the same tools are driven by a slot-filling
state machine with regex extraction (deterministic mode). Add the key and the agent switches to Claude automatically.

## Quick start

```bash
cd loan-eligibility-chatbot
uv venv --python 3.12 .venv            # or: python3.12 -m venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env                   # add ANTHROPIC_API_KEY=... to enable GenAI mode
.venv/bin/uvicorn backend.main:app --reload --port 8000
# open http://localhost:8000 (overview) → "Check my eligibility" → /chat
```

Regenerate data and run the evaluation:

```bash
.venv/bin/python -m data.generate_synthetic --n 300
.venv/bin/python -m eval.run_eval          # GenAI mode if key present
.venv/bin/python -m eval.run_eval --no-llm # deterministic baseline
# -> eval/REPORT.md
```

## Project layout

```
backend/
  main.py        FastAPI app: /api/chat, /api/evaluate, /api/rules, /api/samples, /api/health, static UI
  agent.py       Session + GenAIAgent (Claude tool loop) + DeterministicAgent (fallback) + tools
  rules.py       Eligibility engine: EMI, FOIR, LTV, age-at-maturity, income multiples, counterfactuals
  extractor.py   Regex extraction of facts from EN / HI / Hinglish text (fallback + eval baseline)
  privacy.py     PII masking
  documents.py   Document checklists
  i18n.py        Language detection + templated replies (fallback mode)
frontend/        Chat UI with eligibility dashboard, voice in/out (Web Speech API)
data/
  rules.json     The bank's (synthetic) policy — edit without touching code
  test_cases.json  36 labelled conversations + 15 rule-boundary cases
  generate_synthetic.py -> applicants.csv
eval/run_eval.py Accuracy + latency report
docs/            ARCHITECTURE.md, DEMO_SCRIPT.md, PITCH.md
```

## API

```bash
curl -s localhost:8000/api/chat -H 'content-type: application/json' \
  -d '{"message":"I am 29, salaried, earn 65k, need 6 lakh personal loan for 4 years, cibil 760, no EMIs"}'
```

Response includes `reply`, `evaluation` (status, checks, EMI, FOIR, max eligible, improvements), `profile`,
`documents`, `latency_ms`, `pii_masked`, `mode`.

`POST /api/evaluate {"applicant": {...}}` hits the rules engine directly.

## Configuration

All keys are optional. With none, everything runs on the rules engine.

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Claude (paid) as first choice in the model chain |
| `ANTHROPIC_MODEL` | `claude-opus-5-5` | Claude model when the key above is set |
| `OPENROUTER_API_KEY` | — | Free models via OpenRouter |
| `OPENROUTER_MODEL` | `nvidia/nemotron-3.5-super-vl:free` | Primary free model (fastest with correct tool calling in our tests: ~7 s) |
| `OPENROUTER_FALLBACK_MODELS` | `nvidia/nemotron-3.5-lightning:free,…` | Tried after NVIDIA if the primary is rate-limited |
| `NVIDIA_API_KEY` | — | NVIDIA's free API (Nemotron Ultra), second in the chain |
| `SARVAM_API_KEY` | — | Sarvam AI speech-to-text / text-to-speech for Indian languages; browser speech otherwise |
| `LLM_TURN_BUDGET_S` | `13` | Hard latency budget per reply; past it the rules engine answers, so replies stay < 15 s |
| `LLM_EFFORT` | `low` | Reasoning effort for Claude |
| `RATE_CHAT_PER_MIN` / `RATE_VOICE_PER_MIN` / `RATE_API_PER_MIN` | 20 / 10 / 120 | Per-client rate limits |
| `ALLOWED_ORIGINS` | — (same-origin) | Comma-separated origins allowed to call the API cross-site |

**Model chain:** Claude (if keyed) → OpenRouter free → NVIDIA free → more OpenRouter free → rules engine.
Each step is skipped on rate limit / error / timeout. If a model can't explain a verdict inside the budget,
the engine's own explanation is used ("fast path"), so the decision never waits on a model.

## Tests (attack suite)

```bash
.venv/bin/python tests/run_all.py   # never calls a paid API
```

Invariant fuzzer over 30k random profiles (EMI/FOIR maths, monotonicity, every "you qualify for up to X"
and every improvement suggestion re-checked), NaN/inf/garbage inputs, 81 realistic EN/HI/Hinglish messages,
PII masking, HTTP hardening (rate limits, body limits, headers), multi-turn conversations, labelled eval.

## Verdict categories

- **ELIGIBLE** — all hard rules pass.
- **CONDITIONAL** — eligible for a smaller amount, or passes with a caveat (score near cut-off, collateral needed, tenure clamped).
- **NOT_ELIGIBLE** — a hard rule fails (score, income, age, employment); the reply says what to fix.
- **INCOMPLETE** — still collecting facts.

This is an indicative *soft check*: no bureau enquiry is made and no data is stored.
