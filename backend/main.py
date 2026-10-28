"""FastAPI entry point: JSON API + static chat UI.

Run:  uvicorn backend.main:app --reload --port 8000
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal, Optional, Union

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from . import agent, audit, lenders, simulated, statement, voice
from .documents import required_documents
from .rules import evaluate
from .security import SecurityMiddleware
from .store import sessions

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
log = logging.getLogger("loanmitra")

app = FastAPI(title="LoanMitra — Automated Loan Eligibility Chatbot", version="2.0.0",
              docs_url=None, redoc_url=None, openapi_url=None)  # no public schema browsing in demo/prod
app.add_middleware(SecurityMiddleware)
if ALLOWED_ORIGINS:  # same-origin by default; list partner origins explicitly to allow cross-site calls
    app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type"])


class ChatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: Optional[str] = Field(None, max_length=64)
    message: str = Field(..., min_length=1, max_length=2000)
    language: Literal["auto", "en", "hi", "hinglish", "bn", "ta", "te", "kn", "ml", "mr", "gu", "pa", "od"] = "auto"


class EvaluateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    applicant: dict[str, Union[StrictBool, float, int, str, None]] = Field(..., max_length=30)


class SimConsentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consent: Literal[True]  # explicit applicant consent is mandatory, as it would be for a real bureau / AA call
    mobile_last4: str = Field(..., pattern=r"^[0-9]{4}$")


class ResetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(..., max_length=64)


class TtsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(..., min_length=1, max_length=4000)
    language: Literal["auto", "en", "hi", "hinglish", "bn", "ta", "te", "kn", "ml", "mr", "gu", "pa", "od"] = "en"


@app.get("/api/health")
def health():
    return {"status": "ok", "mode": "genai" if agent.genai_available() else "deterministic",
            "model": agent.MODEL if agent.genai_available() else None,
            "voice": "sarvam" if voice.available() else "browser"}


@app.post("/api/stt")
async def stt(request: Request):
    """Body: raw audio blob from MediaRecorder (audio/webm)."""
    if not voice.available():
        raise HTTPException(503, "Sarvam not configured")
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in voice.ALLOWED_AUDIO_TYPES:
        raise HTTPException(415, "Unsupported audio type")
    audio = await request.body()  # size already bounded by SecurityMiddleware (Content-Length)
    if not audio:
        raise HTTPException(400, "Empty recording")
    try:
        return voice.speech_to_text(audio, content_type)
    except Exception:
        log.exception("speech-to-text failed")
        raise HTTPException(502, "Speech service unavailable, please type instead.")


@app.post("/api/tts")
def tts(body: TtsIn):
    if not voice.available():
        raise HTTPException(503, "Sarvam not configured")
    try:
        return {"audio_wav_base64": voice.text_to_speech(body.text, body.language)}
    except Exception:
        log.exception("text-to-speech failed")
        raise HTTPException(502, "Speech service unavailable.")


@app.post("/api/chat")
def chat(body: ChatIn):
    s, lock = sessions.get_or_create(body.session_id)
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "Your previous message is still being processed.")
    try:
        out = agent.handle_message(s, body.message, body.language)
    finally:
        lock.release()
    out["session_id"] = s.id
    return out


@app.post("/api/reset")
def reset(body: ResetIn):
    s = sessions.get(body.session_id)
    if s:
        s.reset()
    return {"ok": True}


@app.post("/api/evaluate")
def evaluate_direct(body: EvaluateIn):
    """Direct access to the rules engine (used by tests / integrations)."""
    ev = evaluate(body.applicant).as_dict()
    if ev["status"] != "INCOMPLETE":
        ev["documents"] = required_documents(ev["loan_type"], body.applicant.get("employment_type"))
    return ev


@app.get("/api/lenders")
def lender_list():
    """The (synthetic) lender panel with headline rates per product."""
    return lenders.public_list()


@app.post("/api/lenders/compare")
def lender_compare(body: EvaluateIn):
    """Eligibility, rate, EMI and fees at every lender on the panel, best first."""
    return lenders.compare(body.applicant)


@app.post("/api/sim/lenders/{lender_id}/eligibility")
def sim_lender_eligibility(lender_id: str, body: EvaluateIn):
    """SIMULATED lender eligibility API: one lender's decision on one applicant."""
    try:
        return lenders.lender_eligibility(lender_id, body.applicant)
    except KeyError:
        raise HTTPException(404, "Unknown lender")


@app.post("/api/sim/bureau/soft-pull")
def sim_bureau(body: SimConsentIn):
    """SIMULATED credit bureau soft pull (no score impact). Deterministic per mobile_last4."""
    return simulated.bureau_soft_pull(body.mobile_last4)


@app.post("/api/sim/aa/income")
def sim_aa(body: SimConsentIn):
    """SIMULATED Account Aggregator income summary from 6 months of statements."""
    return simulated.aa_income(body.mobile_last4)


STATEMENT_TYPES = {"application/pdf", "text/csv", "text/plain", "application/vnd.ms-excel", "application/octet-stream"}


@app.post("/api/statement/analyze")
async def statement_analyze(request: Request, consent: bool = False, session_id: Optional[str] = None):
    """Analyse an uploaded bank statement (PDF/CSV) in memory. Returns aggregates only; nothing is stored.

    With a session_id, the aggregates are attached to that chat session so the confirmation step can flag
    differences between what the applicant states and what the statement shows."""
    if not consent:
        raise HTTPException(422, "Consent is required to read a bank statement.")
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype not in STATEMENT_TYPES:
        raise HTTPException(415, "Please upload a PDF or CSV statement.")
    data = await request.body()  # size bounded by SecurityMiddleware (Content-Length)
    try:
        result = statement.analyze(data, ctype)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    finally:
        del data
    s, _ = sessions.get_or_create(session_id)
    s.statement = {k: result[k] for k in ("avg_monthly_income", "avg_monthly_emi", "bounced_payments", "months_covered")}
    result["session_id"] = s.id
    session_id = s.id
    audit.record("statement_analyzed", session_id or "anonymous", months=result["months_covered"],
                 income_type=result["income_type"], bounced=result["bounced_payments"])
    return result


@app.get("/api/samples")
def samples():
    """Synthetic applicants shown as quick-start chips in the UI."""
    return [
        {"label": "Salaried, personal loan", "text": "Hi, I'm 29, salaried with a take-home of 65,000 per month. I need a personal loan of 6 lakh for 4 years. My CIBIL is 760 and I have no other EMIs."},
        {"label": "Home loan, tight FOIR", "text": "I want a home loan of 60 lakh for 20 years. The flat costs 70 lakh. I'm 38, self-employed, earning 1.1 lakh a month, credit score 720, and I already pay 25,000 EMI on a car loan."},
        {"label": "Car loan (Hinglish)", "text": "Mujhe 9 lakh ka car loan chahiye 5 saal ke liye, gaadi ki on-road price 10 lakh hai. Main 32 saal ka hoon, salary 55k hai, CIBIL 690, koi EMI nahi."},
        {"label": "Education abroad (Hindi)", "text": "मुझे विदेश में पढ़ाई के लिए 40 लाख का एजुकेशन लोन चाहिए, 10 साल के लिए। मेरी उम्र 23 है। मेरे पिता की आय 1.5 लाख प्रति माह है, उनका क्रेडिट स्कोर 780 है और कोई EMI नहीं है।"},
        {"label": "Low score, rejected", "text": "I'm 45 years old, salaried at 40,000 per month, cibil 640, paying 12,000 EMI. Need 8 lakh personal loan for 5 years."},
    ]


# --- static UI
if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")

    @app.get("/")
    def landing():
        return FileResponse(str(FRONTEND / "landing.html"))

    @app.get("/chat")
    def chat_page():
        return FileResponse(str(FRONTEND / "chat.html"))
