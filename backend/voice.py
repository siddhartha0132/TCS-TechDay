"""Server-side proxy for Sarvam AI speech APIs (Indian-language STT and TTS).

The browser never sees the API key. When SARVAM_API_KEY is unset the UI falls
back to the browser's built-in Web Speech engines.
"""
from __future__ import annotations

import os
import re

import httpx

SARVAM_URL = "https://api.sarvam.ai"
TTS_MAX_CHARS = 1400
EMOJI_AND_MARKS = re.compile(r"[\U0001F300-\U0001FAFF☀-➿•→☐*#_`]")


def available() -> bool:
    return bool(os.getenv("SARVAM_API_KEY"))


def _headers() -> dict[str, str]:
    return {"api-subscription-key": os.environ["SARVAM_API_KEY"]}


def speech_to_text(audio: bytes, content_type: str) -> dict:
    """Transcribe a short recording; Sarvam auto-detects the language."""
    ext = "webm" if "webm" in content_type else "ogg" if "ogg" in content_type else "mp4" if "mp4" in content_type else "wav"
    r = httpx.post(f"{SARVAM_URL}/speech-to-text", headers=_headers(), timeout=30,
                   files={"file": (f"speech.{ext}", audio, content_type or "audio/webm")},
                   data={"language_code": "unknown"})
    r.raise_for_status()
    d = r.json()
    return {"transcript": d.get("transcript", ""), "language_code": d.get("language_code")}


def text_to_speech(text: str, language: str) -> str:
    """Return base64 WAV. Devanagari or language 'hi' -> Hindi voice, otherwise Indian English."""
    clean = EMOJI_AND_MARKS.sub(" ", text)
    clean = re.sub(r"\s+", " ", clean).strip()[:TTS_MAX_CHARS]
    lang = "hi-IN" if language == "hi" or re.search(r"[ऀ-ॿ]", clean) else "en-IN"
    r = httpx.post(f"{SARVAM_URL}/text-to-speech", headers=_headers(), timeout=30,
                   json={"text": clean, "target_language_code": lang})
    r.raise_for_status()
    return r.json()["audios"][0]
