# Evaluation report

- Mode: **deterministic**
- Generated: 2026-10-28 15:42

## A. Rules engine — 17/17 = **100%**

| id | case | expected | got | ok |
|---|---|---|---|---|
| st01 | clean personal | ELIGIBLE | ELIGIBLE | ✅ |
| st02 | score one below cut-off | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ |
| st03 | FOIR exactly at 50% boundary -> CONDITIONAL (margin flag) | CONDITIONAL | CONDITIONAL | ✅ |
| st04 | maturity age over 60 salaried | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ |
| st05 | same but self-employed (limit 65) | ELIGIBLE | ELIGIBLE | ✅ |
| st06 | home LTV 95% -> conditional at 90% cap | CONDITIONAL | CONDITIONAL | ✅ |
| st07 | home clean | ELIGIBLE | ELIGIBLE | ✅ |
| st08 | auto score 650 boundary -> conditional via margin | CONDITIONAL | CONDITIONAL | ✅ |
| st09 | auto short employment vintage | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ |
| st10 | education India under collateral threshold | ELIGIBLE | ELIGIBLE | ✅ |
| st11 | education abroad above collateral threshold -> conditional | CONDITIONAL | CONDITIONAL | ✅ |
| st12 | education co-applicant income too low | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ |
| st13 | missing credit score -> INCOMPLETE | INCOMPLETE | INCOMPLETE | ✅ |
| st14 | string amounts normalised | ELIGIBLE | ELIGIBLE | ✅ |
| st15 | personal above 24x income | CONDITIONAL | CONDITIONAL | ✅ |
| st16 | home FOIR fails alone (70%) | CONDITIONAL | CONDITIONAL | ✅ |
| st17 | same + spouse co-applicant 40k clubbed -> FOIR 43% | ELIGIBLE | ELIGIBLE | ✅ |

## B. Regex extraction baseline (single message) — fields 283/283 = **100%**, verdict 36/36 = **100%**

| id | lang | expected | got | ok | field mismatches |
|---|---|---|---|---|---|
| nl01 | en | ELIGIBLE | ELIGIBLE | ✅ | — |
| nl02 | en | CONDITIONAL | CONDITIONAL | ✅ | — |
| nl03 | hinglish | ELIGIBLE | ELIGIBLE | ✅ | — |
| nl04 | hi | CONDITIONAL | CONDITIONAL | ✅ | — |
| nl05 | en | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ | — |
| nl06 | en | CONDITIONAL | CONDITIONAL | ✅ | — |
| nl07 | en | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ | — |
| nl08 | en | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ | — |
| nl09 | hinglish | ELIGIBLE | ELIGIBLE | ✅ | — |
| nl10 | hi | CONDITIONAL | CONDITIONAL | ✅ | — |
| nl11 | en | ELIGIBLE | ELIGIBLE | ✅ | — |
| nl12 | en | CONDITIONAL | CONDITIONAL | ✅ | — |
| nl13 | en | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ | — |
| nl14 | en | CONDITIONAL | CONDITIONAL | ✅ | — |
| nl15 | en | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ | — |
| nl16 | en | ELIGIBLE | ELIGIBLE | ✅ | — |
| nl17 | en | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ | — |
| nl18 | en | CONDITIONAL | CONDITIONAL | ✅ | — |
| nl19 | en | INCOMPLETE | INCOMPLETE | ✅ | — |
| nl20 | en | INCOMPLETE | INCOMPLETE | ✅ | — |
| nl21 | en | ELIGIBLE | ELIGIBLE | ✅ | — |
| nl22 | en | CONDITIONAL | CONDITIONAL | ✅ | — |
| nl23 | en | CONDITIONAL | CONDITIONAL | ✅ | — |
| nl24 | en | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ | — |
| nl25 | hinglish | ELIGIBLE | ELIGIBLE | ✅ | — |
| nl26 | hi | ELIGIBLE | ELIGIBLE | ✅ | — |
| nl27 | en | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ | — |
| nl28 | en | ELIGIBLE | ELIGIBLE | ✅ | — |
| nl29 | en | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ | — |
| nl30 | en | CONDITIONAL | CONDITIONAL | ✅ | — |
| nl31 | en | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ | — |
| nl32 | en | ELIGIBLE | ELIGIBLE | ✅ | — |
| nl33 | en | CONDITIONAL | CONDITIONAL | ✅ | — |
| nl34 | hinglish | INCOMPLETE | INCOMPLETE | ✅ | — |
| nl35 | en | CONDITIONAL | CONDITIONAL | ✅ | — |
| nl36 | en | CONDITIONAL | CONDITIONAL | ✅ | — |

## C. End-to-end conversation (deterministic) — verdict 36/36 = **100%**

- Replies under 15 s: **69/69** (100%) · latency p50 0 ms · p95 0 ms · max 0 ms
- Average turns to verdict: 1.9
- Replies where the LLM failed and the deterministic fallback answered: **0/69**
- PII masking on labelled cases: ✅

| id | lang | expected | got | ok | turns | max ms |
|---|---|---|---|---|---|---|
| nl01 | en | ELIGIBLE | ELIGIBLE | ✅ | 2 | 0 |
| nl02 | en | CONDITIONAL | CONDITIONAL | ✅ | 2 | 0 |
| nl03 | hinglish | ELIGIBLE | ELIGIBLE | ✅ | 2 | 0 |
| nl04 | hi | CONDITIONAL | CONDITIONAL | ✅ | 2 | 0 |
| nl05 | en | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ | 2 | 0 |
| nl06 | en | CONDITIONAL | CONDITIONAL | ✅ | 2 | 0 |
| nl07 | en | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ | 2 | 0 |
| nl08 | en | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ | 2 | 0 |
| nl09 | hinglish | ELIGIBLE | ELIGIBLE | ✅ | 2 | 0 |
| nl10 | hi | CONDITIONAL | CONDITIONAL | ✅ | 2 | 0 |
| nl11 | en | ELIGIBLE | ELIGIBLE | ✅ | 2 | 0 |
| nl12 | en | CONDITIONAL | CONDITIONAL | ✅ | 2 | 0 |
| nl13 | en | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ | 2 | 0 |
| nl14 | en | CONDITIONAL | CONDITIONAL | ✅ | 2 | 0 |
| nl15 | en | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ | 2 | 0 |
| nl16 | en | ELIGIBLE | ELIGIBLE | ✅ | 2 | 0 |
| nl17 | en | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ | 2 | 0 |
| nl18 | en | CONDITIONAL | CONDITIONAL | ✅ | 2 | 0 |
| nl19 | en | INCOMPLETE | INCOMPLETE | ✅ | 1 | 0 |
| nl20 | en | INCOMPLETE | INCOMPLETE | ✅ | 1 | 0 |
| nl21 | en | ELIGIBLE | ELIGIBLE | ✅ | 2 | 0 |
| nl22 | en | CONDITIONAL | CONDITIONAL | ✅ | 2 | 0 |
| nl23 | en | CONDITIONAL | CONDITIONAL | ✅ | 2 | 0 |
| nl24 | en | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ | 2 | 0 |
| nl25 | hinglish | ELIGIBLE | ELIGIBLE | ✅ | 2 | 0 |
| nl26 | hi | ELIGIBLE | ELIGIBLE | ✅ | 2 | 0 |
| nl27 | en | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ | 2 | 0 |
| nl28 | en | ELIGIBLE | ELIGIBLE | ✅ | 2 | 0 |
| nl29 | en | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ | 2 | 0 |
| nl30 | en | CONDITIONAL | CONDITIONAL | ✅ | 2 | 0 |
| nl31 | en | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ | 2 | 0 |
| nl32 | en | ELIGIBLE | ELIGIBLE | ✅ | 2 | 0 |
| nl33 | en | CONDITIONAL | CONDITIONAL | ✅ | 2 | 0 |
| nl34 | hinglish | INCOMPLETE | INCOMPLETE | ✅ | 1 | 0 |
| nl35 | en | CONDITIONAL | CONDITIONAL | ✅ | 2 | 0 |
| nl36 | en | CONDITIONAL | CONDITIONAL | ✅ | 2 | 0 |

## How to read this

- **A** proves the policy engine matches the hand-written expectations at rule boundaries (score cut-offs, FOIR, LTV, age at maturity).
- **B** is the no-LLM regex baseline on a single free-text message — this is what powers the demo without an API key.
- **C** is the metric that matters for the problem statement: the agent collects what it needs across turns and the final verdict is compared with the label. With `ANTHROPIC_API_KEY` set, section C exercises Claude's understanding of English / Hindi / Hinglish input.
- Verdict categories: ELIGIBLE, CONDITIONAL (eligible for a smaller amount or with a caveat), NOT_ELIGIBLE, INCOMPLETE.