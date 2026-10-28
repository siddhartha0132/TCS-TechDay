# Demo script (≈ 4 minutes)

Run `.venv/bin/uvicorn backend.main:app --port 8000`, open http://localhost:8000 in Chrome (browser-fallback voice needs Chrome/Edge; with `SARVAM_API_KEY` set, any browser with mic access works).
Reset with **New application** between scenes. Keep the dashboard visible — it is half the story.

## 0. Hook (20 s)
"Loan applicants don't know if they qualify, bank staff answer the same questions all day, and a wrong application
costs a hard credit enquiry. LoanMitra answers in seconds, in the applicant's language, with reasons and a plan."

Point at the header badge: **GenAI · claude-…** (or *Deterministic mode* if no key).

## 1. Happy path, one message (40 s)
Click chip **Salaried, personal loan** → the bot replies ELIGIBLE with EMI.
Walk the dashboard: gauge, EMI / FOIR / max eligible, profile filled 8/8, every rule ✓, documents list, ⏱ latency badge.
"Every tick is a real rule from `rules.json`, not something the model made up."

## 2. Conditional + what-if (60 s)
Click chip **Home loan, tight FOIR** → CONDITIONAL: "₹60 L is above what you qualify for, but up to ₹40.9 L…".
Show *What-if & next steps*: extend tenure, close EMIs, add co-applicant income.
Type: `what if I add my wife as co-applicant with 50,000 income?` (GenAI mode) — the agent calls `what_if` and answers.

## 3. Multilingual + voice (50 s)
Click chip **Education abroad (Hindi)** → reply in Hindi, collateral caveat flagged.
Then tap 🎤, say in Hinglish: "Mujhe 3 lakh ka personal loan chahiye 2 saal ke liye, main 35 saal ka hoon, salary 70 hazaar, CIBIL 745, koi EMI nahi."
Toggle 🔊 so the verdict is read aloud.

## 4. Rejection with a path back (30 s)
Click chip **Low score, rejected** → NOT_ELIGIBLE. Point at the reasons (score 640 vs 700, FOIR) and the next steps
(points to gain, EMIs to close, max amount today). "A rejection is not a dead end — it's a to-do list."

## 5. Privacy (15 s)
Type: `My PAN is ABCDE1234F and phone 9876543210, am I eligible?` → badge shows **masked: PAN, phone**.
"Identifiers never reach the model or the logs. No data is stored."

## 6. Accuracy & latency (25 s)
Open `eval/REPORT.md`: rules 17/17, extraction 283/283 fields and 36/36 verdicts, end-to-end 35/36 GenAI (36/36 deterministic),
36/37 replies under 15 s. "The target was 80 %; the engine is deterministic so we can prove it, not estimate it."

## Backup if the API is down
Remove the key from `.env` (or let the auto-fallback kick in) — same flows work in deterministic mode; the badge
turns amber. Mention it as a feature: "the bank's decision logic never depends on an external API being up."
