# Team — who built what, and who presents what

Five members, one module each. The applicant-profile schema and the agent's four tools were agreed first, so all
modules were built in parallel against one contract; `tests/test_suite.py` ran on every change.

| Member | Module | Main files | Shows in the demo | Answers jury questions on |
|---|---|---|---|---|
| 1 | Rules engine & data | `backend/rules.py`, `data/rules.json`, `backend/lenders.py`, `data/lenders.json`, `backend/simulated.py`, `data/generate_synthetic.py` | Rule checks panel, Compare banks | Eligibility logic, FOIR / LTV, accuracy, simulated APIs |
| 2 | GenAI agent | `backend/agent.py`, `backend/extractor.py`, `backend/numbers.py` | A full chat conversation, confirm step | LLM, tool calling, model fallback, < 15 s budget |
| 3 | Voice & languages | `backend/voice.py`, `backend/i18n.py`, `frontend/ui_strings.js`, `data/make_ui_translations.py` | Speak in Marathi; the UI switches language | Speech AI, translation, 12 languages |
| 4 | Frontend & UX | `frontend/landing.*`, `frontend/scene3d.js`, `frontend/chat.html`, `frontend/app.js`, `frontend/styles.css` | Landing page + jury brief, quick form, what-if sliders | UX for every user, accessibility |
| 5 | Privacy, security & testing | `backend/statement.py`, `backend/privacy.py`, `backend/security.py`, `backend/audit.py`, `tests/`, `eval/`, `Dockerfile`, `docs/` | Bank-statement check, PII masking, test results | Privacy (DPDP), security, scaling, deployment |

## Presentation order (about 7 minutes)

| Time | Speaker | What to say / do |
|---|---|---|
| 0:00–1:00 | Member 4 | Landing page: problem, market gap, jury brief scorecard |
| 1:00–2:30 | Member 2 | Chat: one sentence in English → AI collects facts → confirm → verdict |
| 2:30–3:30 | Member 1 | Rule checks with real numbers, improvement plan, compare 4 banks |
| 3:30–4:45 | Member 3 | Speak in Marathi: interface and reply switch to Marathi; voice reply |
| 4:45–6:00 | Member 5 | Upload `demo_statement.pdf`, claim ₹1.2 L → bot flags ₹82,000 and ₹9,300 EMIs; PII masking; test results |
| 6:00–7:00 | Member 4 | Feasibility & scaling, wrap-up; questions shared by module (table above) |
