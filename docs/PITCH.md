# LoanMitra — pitch deck outline (10 slides)

Mapped to the jury's rubric: Relevance 30 · Innovation 15 · Feasibility & scalability 15 · AI/ML/GenAI 20 · Teamwork 20.

---

### 1. Title
**LoanMitra** — Automated Loan Eligibility Chatbot · TCS Technology Day · Team ___

### 2. The problem (Relevance)
- Eligibility criteria are opaque: income, score, FOIR, LTV, age, tenure — different per product.
- Applicants apply blind → rejections → hard enquiries → lower scores → more rejections.
- Bank staff spend hours on repetitive eligibility questions; static FAQs and calculators don't adapt.
- Result: funnel drop-off, rework, support cost, slow turnaround.

### 3. What we built (Relevance)
One chatbot that: understands EN / हिंदी / Hinglish (text + voice) → collects the facts → runs the bank's rules →
replies in seconds with verdict, reasons, EMI, next steps, document list. Screenshot of the UI.

### 4. Live demo
(see DEMO_SCRIPT.md) — happy path · conditional with what-if · Hindi + voice · rejection with a plan · PII masking.

### 5. How it works (AI/ML/GenAI)
Diagram from ARCHITECTURE.md. Single agent, three tools, deterministic rules engine.
"GenAI understands and explains; code decides." Claude tool-use, prompt caching, effort tuning for < 15 s,
automatic fallback brain if the API is unavailable.

### 5b. Market gap — what exists vs. what doesn't (Relevance + Innovation)
| | Eligibility calculators (lender sites) | Loan marketplaces | Bank chatbots (e.g. EVA, SIA) | LoanMitra |
|---|---|---|---|---|
| Conversation, no forms | ✕ | ✕ | ✓ | ✓ |
| Why, rule by rule | ✕ one number | ~ | ✕ FAQs | ✓ |
| Plan to become eligible | ✕ | ✕ | ✕ | ✓ |
| Hindi / Hinglish + voice | ✕ | ✕ | ~ some Hindi | ✓ |
| No credit-score impact | ✓ | ✓ soft check | ✓ | ✓ |
| Auditable rules | ~ | ✕ | ✕ | ✓ |

- ~30% of Indians have faced a loan/card rejection, many without knowing why (Business Today, May 2026).
- Lender calculators ask for age, income, obligations and return a single number (e.g. Bajaj Finserv, SMFG, Fibe pages).
- RBI fair-practices guidance expects main rejection reasons to be conveyed — LoanMitra makes them visible *before* applying.
- Caveat for Q&A: comparison is by tool category from public descriptions; individual products vary.

### 6. What makes it different (Innovation)
- **Counterfactual next steps**: not "no", but "₹40.9 L yes, or ₹60 L if you add ₹30 k co-applicant income".
- **What-if conversations** without re-entering data.
- **Soft check** — no bureau hit, nothing stored, PII masked live.
- **Multilingual + voice** for Bharat, not just metro English.
- **Explainability panel**: every rule, pass/fail, with the numbers.

### 7. Accuracy & performance (AI/ML + Feasibility)
Table from eval/REPORT.md: rules 15/15 · extraction fields % · end-to-end verdicts % on 36 labelled multilingual
cases · 100 % replies under 15 s · p50 latency. 300 synthetic applicants generated for testing.

### 8. Feasibility & scale
- Policy is data (`rules.json`) → product teams change cut-offs without a release.
- Stateless API, in-memory sessions → Redis + N replicas; engine is pure Python, thousands of evals/sec.
- Drop-in points for real bureau / KYC / OCR APIs behind the same tool signatures.
- Runs on-prem or cloud; model is configurable; deterministic mode keeps the service up without an LLM.

### 9. Team (Teamwork)
Who owned what: rules & data · agent & prompts · UI & voice · eval & docs · demo & pitch. How we split and
integrated (shared tool interface made parallel work possible).

### 10. Next steps & ask
Real policy integration · pre-approved offers for existing customers · WhatsApp channel · regional languages
beyond Hindi · adverse-action explanations aligned to RBI fair-practice code.

---

**One-line close:** "Every applicant gets a yes, a smaller yes, or a plan — in their language, in seconds, with nothing stored."
