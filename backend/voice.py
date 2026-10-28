"""Server-side proxy for Sarvam AI speech APIs (Indian-language STT and TTS).

The browser never sees the API key. When SARVAM_API_KEY is unset the UI falls
back to the browser's built-in Web Speech engines.
"""
from __future__ import annotations

import os
import re

from concurrent.futures import ThreadPoolExecutor

import httpx

SARVAM_URL = "https://api.sarvam.ai"
TTS_MAX_CHARS = 1400
ALLOWED_AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/mp4", "audio/wav", "audio/x-wav", "audio/wave", "audio/mpeg"}
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


REGIONAL = {"bn", "ta", "te", "kn", "ml", "mr", "gu", "pa", "od"}


def _code(lang: str) -> str:
    return "en-IN" if lang in ("en", "auto", "hinglish") else f"{lang}-IN"


def _translate_chunk(chunk: str, source: str, target: str) -> str:
    r = httpx.post(f"{SARVAM_URL}/translate", headers=_headers(), timeout=8,
                   json={"input": chunk, "source_language_code": _code(source), "target_language_code": _code(target)})
    r.raise_for_status()
    return r.json()["translated_text"]


def translate(text: str, source: str, target: str) -> str:
    """Sarvam translation. Lines are packed into <=900-char chunks translated in parallel (usually one call)."""
    chunks, cur = [], ""
    for line in text.split("\n"):
        if cur and len(cur) + len(line) + 1 > 900:
            chunks.append(cur)
            cur = ""
        cur = f"{cur}\n{line}" if cur else line[:900]
    if cur:
        chunks.append(cur)
    with ThreadPoolExecutor(max_workers=4) as pool:
        return "\n".join(pool.map(lambda c: _translate_chunk(c, source, target), chunks))


def text_to_speech(text: str, language: str) -> str:
    """Return base64 WAV in the reply's language (Indian-language voices; Indian English otherwise)."""
    clean = EMOJI_AND_MARKS.sub(" ", text)
    clean = re.sub(r"\s+", " ", clean).strip()[:TTS_MAX_CHARS]
    if language in REGIONAL:
        lang = f"{language}-IN"
    else:
        lang = "hi-IN" if language == "hi" or re.search(r"[\u0900-\u097F]", clean) else "en-IN"
    r = httpx.post(f"{SARVAM_URL}/text-to-speech", headers=_headers(), timeout=30,
                   json={"text": clean, "target_language_code": lang})
    r.raise_for_status()
    return r.json()["audios"][0]
