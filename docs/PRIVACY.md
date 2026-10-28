# Privacy, consent and audit

This is a **demo on synthetic data**. Below is what the build does today, and what a bank would add before real use
under India's Digital Personal Data Protection Act, 2023 (DPDP Act). This is a design note, not legal advice.

## What the demo does

| Area | Behaviour |
|---|---|
| Data minimisation | A soft eligibility check needs no identifiers. The bot never asks for PAN, Aadhaar, phone, account or card numbers. |
| PII masking | If a user types identifiers anyway, `backend/privacy.py` masks them **before** the text reaches a model, the conversation history, logs or the translation service. Checksums (Verhoeff, Luhn) and context keep real rupee amounts intact. |
| Storage | Sessions live in memory only and expire after 1 hour; nothing a user types is written to disk. |
| Explicit confirmation | No verdict is shown until the applicant confirms the exact values the engine will use. |
| Consent for data pulls | The simulated credit-bureau and Account Aggregator APIs reject any request without `consent: true`. |
| Audit trail | `logs/audit.jsonl` records each decision: time, hashed session id, loan type, verdict, policy version, mode, latency, counts of masked items and warnings. **No chat text, amounts or identifiers.** |
| Third parties | Masked text may be sent to the configured AI provider (OpenRouter / NVIDIA / Anthropic) and to Sarvam AI for voice and translation. |

## What a bank must add before real deployment

1. **Notice and consent** (DPDP s.5–6): a clear purpose statement ("indicative loan-eligibility check"), the data
   used, the processors involved (AI and speech providers) and how to withdraw consent, shown before the first message.
2. **Processor agreements** with every AI / speech / translation provider: no training on customer data, retention
   limits, data location.
3. **Retention and deletion policy** for audit logs and any stored applications; a way for users to request erasure.
4. **Real consent artefacts** for bureau pulls and Account Aggregator (RBI AA framework / Sahamati consent flow),
   replacing the simulated `consent: true` flag.
5. **Access controls** on audit logs and admin endpoints; security review of the deployed environment.
6. **Grievance officer** contact, as the Act requires.
