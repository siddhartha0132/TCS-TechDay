# Evaluation report

- Mode: **genai** (model `nvidia/nemotron-3.5-super-vl:free`, effort `low`)
- Generated: 2026-10-28 13:40

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

## C. End-to-end conversation (genai) — verdict 35/36 = **97%**

- Replies under 15 s: **36/37** (97%) · latency p50 13003 ms · p95 13808 ms · max 18891 ms
- Average turns to verdict: 1.0
- Replies where the LLM failed and the deterministic fallback answered: **17/37** ⚠️ section C does not reflect GenAI accuracy
- PII masking on labelled cases: ✅

| id | lang | expected | got | ok | turns | max ms |
|---|---|---|---|---|---|---|
| nl01 | en | ELIGIBLE | ELIGIBLE | ✅ | 1 | 13024 |
| nl02 | en | CONDITIONAL | CONDITIONAL | ✅ | 1 | 13004 |
| nl03 | hinglish | ELIGIBLE | ELIGIBLE | ✅ | 1 | 13808 |
| nl04 | hi | CONDITIONAL | CONDITIONAL | ✅ | 1 | 13004 |
| nl05 | en | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ | 1 | 10932 |
| nl06 | en | CONDITIONAL | CONDITIONAL | ✅ | 1 | 11571 |
| nl07 | en | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ | 1 | 7227 |
| nl08 | en | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ | 1 | 13003 |
| nl09 | hinglish | ELIGIBLE | ELIGIBLE | ✅ | 1 | 13004 |
| nl10 | hi | CONDITIONAL | CONDITIONAL | ✅ | 1 | 9362 |
| nl11 | en | ELIGIBLE | ELIGIBLE | ✅ | 1 | 13003 |
| nl12 | en | CONDITIONAL | CONDITIONAL | ✅ | 1 | 18891 |
| nl13 | en | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ | 1 | 7968 |
| nl14 | en | CONDITIONAL | CONDITIONAL | ✅ | 1 | 5980 |
| nl15 | en | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ | 1 | 13005 |
| nl16 | en | ELIGIBLE | ELIGIBLE | ✅ | 1 | 13957 |
| nl17 | en | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ | 1 | 7665 |
| nl18 | en | CONDITIONAL | CONDITIONAL | ✅ | 1 | 11694 |
| nl19 | en | INCOMPLETE | INCOMPLETE | ✅ | 1 | 4333 |
| nl20 | en | INCOMPLETE | INCOMPLETE | ✅ | 1 | 3029 |
| nl21 | en | ELIGIBLE | ELIGIBLE | ✅ | 1 | 13003 |
| nl22 | en | CONDITIONAL | CONDITIONAL | ✅ | 1 | 8646 |
| nl23 | en | CONDITIONAL | CONDITIONAL | ✅ | 1 | 7609 |
| nl24 | en | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ | 1 | 13005 |
| nl25 | hinglish | ELIGIBLE | ELIGIBLE | ✅ | 1 | 13005 |
| nl26 | hi | ELIGIBLE | ELIGIBLE | ✅ | 1 | 12315 |
| nl27 | en | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ | 2 | 13004 |
| nl28 | en | ELIGIBLE | ELIGIBLE | ✅ | 1 | 13004 |
| nl29 | en | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ | 1 | 13003 |
| nl30 | en | CONDITIONAL | CONDITIONAL | ✅ | 1 | 12066 |
| nl31 | en | NOT_ELIGIBLE | NOT_ELIGIBLE | ✅ | 1 | 13005 |
| nl32 | en | ELIGIBLE | ELIGIBLE | ✅ | 1 | 13557 |
| nl33 | en | CONDITIONAL | CONDITIONAL | ✅ | 1 | 13004 |
| nl34 | hinglish | INCOMPLETE | CONDITIONAL | ❌ | 1 | 8185 |
| nl35 | en | CONDITIONAL | CONDITIONAL | ✅ | 1 | 13005 |
| nl36 | en | CONDITIONAL | CONDITIONAL | ✅ | 1 | 6715 |

## How to read this

- **A** proves the policy engine matches the hand-written expectations at rule boundaries (score cut-offs, FOIR, LTV, age at maturity).
- **B** is the no-LLM regex baseline on a single free-text message — this is what powers the demo without an API key.
- **C** is the metric that matters for the problem statement: the agent collects what it needs across turns and the final verdict is compared with the label. With `ANTHROPIC_API_KEY` set, section C exercises Claude's understanding of English / Hindi / Hinglish input.
- Verdict categories: ELIGIBLE, CONDITIONAL (eligible for a smaller amount or with a caveat), NOT_ELIGIBLE, INCOMPLETE.