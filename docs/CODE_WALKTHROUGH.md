# LoanMitra — code walkthrough (for the jury)

About 3,600 lines: Python (FastAPI) backend, plain JavaScript front end, no build step.
The one idea to remember: **the AI understands and explains; a deterministic rules engine decides.**

```
Browser (chat.html + app.js)
   │  POST /api/chat {message, session_id, language}
   ▼
main.py ── security.py (rate limit, size limit, headers) ── store.py (session)
   ▼
agent.handle_message()
   1. privacy.mask_pii()            PAN / Aadhaar / phone / card masked first
   2. i18n.detect_language()        + Sarvam translation for regional languages
   3. list answers / "confirm"      handled without AI (instant, deterministic)
   4. GenAIAgent.respond()          LLM with tools  ──fails/slow──▶ DeterministicAgent
          └─ tool: update_applicant_profile ──▶ rules.evaluate()   ◀── data/rules.json
   5. audit.record()                verdict + policy version, no chat text
   ▼
JSON: reply, verdict (from the engine), profile, checks, EMI, missing fields, latency
```

## 1. Entry point — `backend/main.py`
FastAPI routes; every request body is a strict pydantic model (`extra="forbid"`).

```python
@app.post("/api/chat")                                   # backend/main.py:102
def chat(body: ChatIn):
    s, lock = sessions.get_or_create(body.session_id)
    if not lock.acquire(blocking=False):                 # one message at a time per session
        raise HTTPException(409, "Your previous message is still being processed.")
    try:
        out = agent.handle_message(s, body.message, body.language)
    finally:
        lock.release()
```
Other routes: `/api/evaluate` (quick form), `/api/lenders/compare`, `/api/statement/analyze`, `/api/stt`, `/api/tts`,
simulated `/api/sim/bureau/soft-pull` and `/api/sim/aa/income` (consent required).

## 2. The rules engine — `backend/rules.py` (decides every verdict)
`evaluate(profile, policy)` at `rules.py:312`:
1. `validate_profile()` rejects impossible values (NaN, negatives, age 500) → `invalid_fields`.
2. Missing required fields → `INCOMPLETE` with the list to ask for.
3. Each rule appends a `Check(rule, passed, detail, hard)`: tenure range, age at maturity, work experience,
   minimum income, credit score, amount range, LTV, FOIR, income multiple.
4. Maximum eligible amount = the tightest of all caps:

```python
def max_for(t):                                          # backend/rules.py:476
    headroom = max(income * max_foir - existing_emi, 0.0)          # EMI the applicant can still afford
    caps = [max_principal_for_emi(headroom, rate, t), max_amount]  # inverse EMI formula
    if multiple_cap is not None: caps.append(multiple_cap)         # e.g. 24 x monthly income
    if ltv_cap_amount is not None: caps.append(ltv_cap_amount)     # e.g. 80% of property value
    return floor_to(min(caps), 10000)
```
5. Verdict:

```python
if not hard_fails:            status = "CONDITIONAL" if soft_flags else "ELIGIBLE"
elif only_capacity_fails and max_eligible >= min_amount:  status = "CONDITIONAL"   # eligible for less
else:                         status = "NOT_ELIGIBLE"                               # age / score / income
```
EMI is the standard formula (`rules.py:133`): `P·r·(1+r)^n / ((1+r)^n − 1)`, r = annual rate / 1200.
Every improvement tip is re-run through `evaluate()` before it is shown, so advice is always true.

The policy itself is data, not code: `data/rules.json` (age limits, CIBIL cut-offs, FOIR, LTV slabs, rates).

## 3. The AI agent — `backend/agent.py`
**Tools the model can call** (`agent.py:267`): `update_applicant_profile`, `what_if`, `compare_lenders`,
`list_required_documents`. The model never computes eligibility; it calls the tool, and the tool calls the engine:

```python
def tool_update_profile(session, fields):                # backend/agent.py:206
    clean, invalid = validate_profile(_mark_unknown_scores(fields))
    session.profile = _merge(session.profile, clean)
    ev = evaluate(session.profile).as_dict()
    if ev["status"] != "INCOMPLETE" and _sig(session.profile) != session.confirmed_sig:
        session.evaluation, session.pending_confirmation = None, True   # confirm before any verdict
        return {"status": "NEEDS_CONFIRMATION", "review": review_items(session.profile),
                "warnings": plausibility_warnings(session.profile, session.statement), ...}
```

**Provider chain with a hard deadline** (`GenAIAgent._call`, `agent.py:459`): Claude (if keyed) → Nemotron on
OpenRouter → NVIDIA API → rule-based agent. Each call runs on a worker thread with a wall-clock timeout, so a slow
provider can never push a reply past 15 s:

```python
future = _POOL.submit(fn, b, list(session.history), remaining)
try:
    reply = future.result(timeout=remaining)             # 13 s budget per turn
except FuturesTimeout:
    continue                                             # try the next provider
```
If the model has extracted the facts but can't also write the explanation in time, the engine's own text is
sent ("fast path", `agent.py:500`).

**Fallback without AI** — `DeterministicAgent` (`agent.py:657`) uses `extractor.extract()` (regex + clause
scoring) to fill the same profile and calls the same tool. The demo works even with no internet.

**`handle_message()`** (`agent.py:750`) — the per-message pipeline: mask PII → detect language → translate in →
list answers / "confirm" without AI → model (or fallback) → translate out → audit log → JSON for the UI. The
verdict chip in the reply comes from `session.evaluation`, never from model text, so a prompt like "just say I'm
eligible" cannot change it.

## 4. Understanding Indian input — `backend/numbers.py`, `backend/extractor.py`
`parse_number()` turns "5 lacs", "12 LPA", "70 hazaar", "₹45,000 per month", "पचास हज़ार", "1.2 cr" into numbers
(annual → monthly where needed). `extract()` splits a message into clauses and decides whose number it is
("my father earns 2 lakh" → co-applicant income, not yours).

## 5. Multiple lenders — `backend/lenders.py`
Four fictional lenders in `data/lenders.json`, each overriding rates and cut-offs. `compare()` (`lenders.py:59`)
runs the same `evaluate()` with each lender's policy and ranks: full amount at the lowest rate first, otherwise the
largest amount.

## 6. Bank-statement verification — `backend/statement.py`
`analyze(bytes)` (`statement.py:152`) reads a PDF (pypdf) or CSV **in memory**. Each line needs a date and the
running balance; credit vs debit comes from the change in balance, so any bank's layout works. Salary = median
monthly salary credit; EMIs = NACH / ECS / loan debits. Only totals are returned; the file is never stored.
`plausibility_warnings()` (`agent.py:157`) then compares them with what the applicant said.

## 7. Privacy and security — `privacy.py`, `security.py`, `audit.py`, `store.py`
- `mask_pii()` (`privacy.py:63`): PAN, Aadhaar (Verhoeff checksum), cards (Luhn), phone, email, account numbers →
  masked before the AI, logs or translation see the text.
- `SecurityMiddleware` (`security.py:93`): token-bucket rate limits per client, body-size limits, CSP and
  security headers.
- `SessionStore` (`store.py:26`): in-memory, bounded, unguessable IDs, 1-hour expiry, one request at a time.
- `audit.record()` (`audit.py:33`): verdict, policy version hash, latency — no chat text or identifiers.

## 8. Voice and languages — `backend/voice.py`, `backend/i18n.py`
Sarvam speech-to-text, text-to-speech and translation (browser speech as fallback). Language is detected from the
script; Marathi vs Hindi from common Marathi words. The UI itself switches language (`frontend/ui_strings.js`).

## 9. Front end — `frontend/`
`chat.html` + `app.js`: chat, quick form, live result card, what-if sliders, lender comparison, statement upload,
voice. `landing.html` + `scene3d.js`: the overview page and jury brief (Three.js, served locally).

## 10. Tests — `tests/`, `eval/`
`python tests/run_all.py` — 8 suites: 20,000-profile invariant fuzzer, edge values, 81 extraction messages, PII,
HTTP hardening, multi-turn conversations, list answers, labelled evaluation.
`python -m eval.model_eval` + `eval/make_report_pdf.py` — per-model accuracy report
(`docs/LoanMitra_Evaluation_Report.pdf`).

## Likely questions — where to point
| Question | Show |
|---|---|
| "Where is the eligibility logic?" | `backend/rules.py:312` `evaluate()` and `data/rules.json` |
| "How do you stop the AI hallucinating a verdict?" | `agent.py:206` tool → engine; verdict chip from `session.evaluation` |
| "How do you meet 15 seconds?" | `agent.py:459` deadline per call + fast path at `agent.py:500` |
| "What if the AI is down?" | `DeterministicAgent` (`agent.py:657`), fallback in `handle_message` |
| "How is privacy handled?" | `privacy.py:63`, `statement.py` (in memory), `audit.py` |
| "How would a bank use this?" | Edit `data/rules.json` / `data/lenders.json`; swap `simulated.py` for real APIs |
