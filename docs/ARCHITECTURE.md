# Architecture

## One agent, two brains, one rules engine

```
 Applicant (text / voice, EN · HI · Hinglish)
        │
        ▼
 ┌──────────────┐    masked text     ┌──────────────────────────────┐
 │  PII guard   │ ─────────────────▶ │  Single agent (session)      │
 │ privacy.py   │                    │                              │
 └──────────────┘                    │  GenAI brain: Claude +tools  │
                                     │  Deterministic brain: slots  │
                                     └──────────┬───────────────────┘
                                                │ tool calls
                     ┌──────────────────────────┼──────────────────────────┐
                     ▼                          ▼                          ▼
          update_applicant_profile           what_if              list_required_documents
                     │                          │                          │
                     ▼                          ▼                          ▼
              ┌───────────────────────────────────────────┐        documents.py
              │  Rules engine  rules.py  ←  rules.json    │
              │  EMI · FOIR · LTV · age-at-maturity ·     │
              │  income multiple · counterfactuals        │
              └───────────────────────────────────────────┘
                                                │
                                                ▼
                        reply + evaluation + profile + latency  →  UI dashboard
```

### Why the LLM never decides eligibility

Banks need decisions that are **repeatable, explainable and auditable**. An LLM is excellent at understanding
"Mujhe 9 lakh ka car loan chahiye, salary 55k hai" and at explaining a result kindly, but it should not be the
thing that says yes or no. So:

- **Understanding + explanation = GenAI.** Claude extracts facts from messy multilingual input, decides what to
  ask next, and phrases the verdict and next steps for the person in front of it.
- **Decision = code.** `evaluate()` in `rules.py` takes a profile and returns the verdict, every rule checked
  (pass / fail / warning with the numbers), EMI, FOIR, the maximum eligible amount, and improvement steps.
  Policy lives in `data/rules.json`; a product manager can change a cut-off without a deploy.

This split is also what makes the **80%+ accuracy** target measurable: the eval compares the engine's verdict on
the facts the agent collected against the verdict on human-labelled facts.

### The GenAI brain (`GenAIAgent`)

- Claude via the Anthropic Python SDK, manual tool loop (`client.beta.messages.create`), max 4 tool rounds.
- `output_config.effort = low` keeps a full verdict turn to a few seconds; raise it if you prefer richer prose.
- System prompt is cached (`cache_control: ephemeral`) and carries a short policy snapshot so the model can set
  expectations before calling the tool.
- Server-side refusal fallback (`fallbacks: "default"`) so a false-positive safety refusal degrades to another
  model instead of a dead turn.
- If the API errors (quota, network), the request is **re-answered by the deterministic brain** and the UI shows
  the mode badge — the demo never stalls.

### The deterministic brain (`DeterministicAgent`)

Slot-filling: extract whatever facts are in the message (`extractor.py`, regex over EN / HI / Hinglish number
words like *lakh*, *hazaar*, *करोड़*), merge into the profile, run the engine, and either ask for the first
missing field or render the verdict with `i18n.py` templates. It shares the same tool functions as the GenAI
brain, so the dashboard and the eval harness are identical in both modes.

### Session & privacy

- Sessions are in-process dictionaries with a 1-hour TTL. Nothing is written to disk.
- `privacy.py` masks PAN, Aadhaar, phone, email, account and card numbers *before* the text reaches the agent,
  the history, or the logs. The UI shows what was masked.
- The bot never asks for identifiers: a soft check needs none.

### Counterfactuals ("what-if")

For every failed capacity rule the engine computes the fix, not just the failure:

| Failure | Computed next step |
|---|---|
| FOIR too high | max amount at this tenure; amount at the longest tenure; EMIs to close; co-applicant income needed |
| LTV too high | extra down payment required |
| Score below cut-off | points to gain + how |
| Age at maturity | tenure that would close before the age limit |
| Amount above product/multiple cap | the cap, as an offer |

`what_if` lets the user explore ("and if I take 7 years?") without changing the saved profile.

### Latency budget (< 15 s)

Deterministic mode: ~1 ms. GenAI mode: one model call for a question turn, two for a verdict turn
(tool call + explanation). Latency is measured server-side per reply and displayed in the UI.

### Scaling notes

- Stateless API apart from the session map → put sessions in Redis and run N replicas.
- Rules engine is pure Python with no I/O; thousands of evaluations per second per core.
- Replace `rules.json` with the bank's real policy engine or a BRMS call behind the same `evaluate()` signature.
- Swap `extractor.py` / `documents.py` for KYC, bureau and OCR APIs when going from synthetic to live data.
