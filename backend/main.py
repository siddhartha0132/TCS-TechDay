"""FastAPI entry point: JSON API + static chat UI.

Run:  uvicorn backend.main:app --reload --port 8000
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import agent, voice
from .documents import required_documents
from .rules import RULES, evaluate

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SESSION_TTL_S = 60 * 60

app = FastAPI(title="LoanMitra — Automated Loan Eligibility Chatbot", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_sessions: dict[str, agent.Session] = {}


def _session(session_id: Optional[str]) -> agent.Session:
    now = time.time()
    for sid in [s for s, v in _sessions.items() if now - v.updated > SESSION_TTL_S]:
        _sessions.pop(sid, None)  # memory-only sessions expire; nothing is written to disk
    if session_id and session_id in _sessions:
        return _sessions[session_id]
    s = agent.Session()
    _sessions[s.id] = s
    return s


class ChatIn(BaseModel):
    session_id: Optional[str] = None
    message: str = Field(..., min_length=1, max_length=2000)
    language: str = "auto"  # auto | en | hi | hinglish


class EvaluateIn(BaseModel):
    applicant: dict[str, Any]


class TtsIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    language: str = "en"


@app.get("/api/health")
def health():
    return {"status": "ok", "mode": "genai" if agent.genai_available() else "deterministic",
            "provider": agent.provider(), "model": agent.MODEL if agent.genai_available() else None,
            "voice": "sarvam" if voice.available() else "browser"}


@app.post("/api/stt")
async def stt(request: Request):
    """Body: raw audio blob from MediaRecorder (audio/webm)."""
    if not voice.available():
        raise HTTPException(503, "Sarvam not configured")
    audio = await request.body()
    if not audio or len(audio) > 10 * 1024 * 1024:
        raise HTTPException(400, "empty or too large recording")
    try:
        return voice.speech_to_text(audio, request.headers.get("content-type", "audio/webm"))
    except Exception as exc:
        raise HTTPException(502, f"speech-to-text failed: {type(exc).__name__}")


@app.post("/api/tts")
def tts(body: TtsIn):
    if not voice.available():
        raise HTTPException(503, "Sarvam not configured")
    try:
        return {"audio_wav_base64": voice.text_to_speech(body.text, body.language)}
    except Exception as exc:
        raise HTTPException(502, f"text-to-speech failed: {type(exc).__name__}")


@app.post("/api/chat")
def chat(body: ChatIn):
    s = _session(body.session_id)
    out = agent.handle_message(s, body.message, body.language)
    out["session_id"] = s.id
    return out


@app.post("/api/reset")
def reset(body: dict):
    s = _sessions.get(body.get("session_id", ""))
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


@app.get("/api/rules")
def rules():
    return RULES


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
    def index():
        return FileResponse(str(FRONTEND / "index.html"))
