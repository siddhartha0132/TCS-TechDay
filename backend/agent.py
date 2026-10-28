"""Single-agent conversation layer.

Two interchangeable brains behind one interface:

* GenAIAgent      - Claude with tool use. The model understands free-form,
                    multilingual input and explains results; every verdict
                    still comes from the deterministic rules engine via tools.
* DeterministicAgent - slot-filling state machine with regex extraction and
                    templated replies. Used when no API key is configured, so
                    the demo always works.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from dotenv import load_dotenv

from . import i18n
from .documents import required_documents
from .extractor import extract
from .privacy import mask_pii
from .rules import REQUIRED_FIELDS, FIELD_LABELS, RULES, evaluate, fmt_inr, normalize_profile

load_dotenv()

EFFORT = os.getenv("LLM_EFFORT", "low")  # low keeps replies well under the 15 s target
MAX_TOOL_ROUNDS = 4
OPENROUTER_BASE_URL = "https://openrouter.ai/api"


def provider() -> Optional[str]:
    """'anthropic' (direct key) > 'openrouter' > None (deterministic mode)."""
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENROUTER_API_KEY"):
        return "openrouter"
    return None


def genai_available() -> bool:
    return provider() is not None


def model_name() -> str:
    name = os.getenv("LLM_MODEL") or "claude-opus-5-5"
    if provider() == "openrouter" and "/" not in name:
        # Anthropic IDs (claude-opus-5-5) -> OpenRouter IDs (anthropic/claude-opus-5.5)
        name = "anthropic/" + re.sub(r"-(\d+)-(\d+)$", r"-\1.\2", name)
    return name


MODEL = model_name()


# ------------------------------------------------------------------ session
@dataclass
class Session:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    lang: str = "en"
    profile: dict[str, Any] = field(default_factory=dict)
    evaluation: Optional[dict] = None
    expected_field: Optional[str] = None
    history: list[dict] = field(default_factory=list)  # LLM message history (masked text only)
    transcript: list[dict] = field(default_factory=list)
    updated: float = field(default_factory=time.time)

    def reset(self) -> None:
        self.profile, self.evaluation, self.expected_field, self.history = {}, None, None, []


# ------------------------------------------------------------------ tools (shared by both brains)
def tool_update_profile(session: Session, fields: dict[str, Any]) -> dict:
    """Merge newly learned facts and re-run the rules engine."""
    clean = normalize_profile(fields)
    # 'unknown' credit score -> policy default 700 so the conversation can continue
    for k in ("credit_score", "co_applicant_credit_score"):
        if k in fields and clean.get(k) is None:
            clean[k] = 700.0
    session.profile.update({k: v for k, v in clean.items() if v is not None})
    ev = evaluate(session.profile).as_dict()
    session.evaluation = ev if ev["status"] != "INCOMPLETE" else session.evaluation
    out = dict(ev)
    out["profile"] = session.profile
    if ev["status"] != "INCOMPLETE":
        out["documents"] = required_documents(session.profile.get("loan_type", ""), session.profile.get("employment_type"))
    return out


def tool_what_if(session: Session, changes: dict[str, Any]) -> dict:
    """Hypothetical re-evaluation without changing the saved profile."""
    trial = dict(session.profile)
    trial.update({k: v for k, v in normalize_profile(changes).items() if v is not None})
    return evaluate(trial).as_dict()


def tool_documents(loan_type: str, employment_type: Optional[str]) -> dict:
    return {"documents": required_documents(loan_type, employment_type)}


TOOLS = [
    {
        "name": "update_applicant_profile",
        "description": (
            "Record facts the applicant has shared and run the bank's eligibility rules. Call this whenever the user "
            "gives ANY new detail (loan type, amount, tenure, age, income, employment, credit score, EMIs, asset value, "
            "co-applicant details). Returns the current verdict (ELIGIBLE / CONDITIONAL / NOT_ELIGIBLE) with reasons and "
            "next steps, or INCOMPLETE with the list of missing fields you should ask for next. Amounts are in INR; "
            "you may pass strings like '5 lakh' or '1.2 cr'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "loan_type": {"type": "string", "enum": ["personal", "home", "auto", "education"]},
                "loan_amount": {"type": ["number", "string"], "description": "Requested loan amount in INR"},
                "tenure_years": {"type": "number"},
                "age": {"type": "number"},
                "monthly_income": {"type": ["number", "string"], "description": "Applicant net monthly income in INR"},
                "employment_type": {"type": "string", "enum": ["salaried", "self_employed"]},
                "employment_months": {"type": "number", "description": "Total work experience in months, if mentioned"},
                "credit_score": {"type": ["number", "string"], "description": "300-900; pass 'unknown' if the user doesn't know"},
                "existing_emi": {"type": ["number", "string"], "description": "Total existing monthly EMIs in INR, 0 if none"},
                "property_value": {"type": ["number", "string"], "description": "Home loan: property value in INR"},
                "vehicle_price": {"type": ["number", "string"], "description": "Car loan: on-road price in INR"},
                "study_abroad": {"type": "boolean", "description": "Education loan: true if studying outside India"},
                "co_applicant_income": {"type": ["number", "string"],
                                        "description": "Co-applicant (spouse/parent) net monthly income; required for education loans, optional for others (clubbed with applicant income)"},
                "co_applicant_credit_score": {"type": ["number", "string"]},
                "co_applicant_existing_emi": {"type": ["number", "string"]},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "what_if",
        "description": (
            "Answer a hypothetical: re-run eligibility with some values changed (e.g. longer tenure, smaller amount, "
            "higher score, co-applicant added) WITHOUT saving the changes. Use when the user asks 'what if...'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"changes": {"type": "object", "description": "Fields to override, same keys as update_applicant_profile"}},
            "required": ["changes"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_required_documents",
        "description": "Checklist of documents needed for a given loan type and employment type.",
        "input_schema": {
            "type": "object",
            "properties": {
                "loan_type": {"type": "string", "enum": ["personal", "home", "auto", "education"]},
                "employment_type": {"type": "string", "enum": ["salaried", "self_employed"]},
            },
            "required": ["loan_type"],
            "additionalProperties": False,
        },
    },
]

POLICY_SUMMARY = "\n".join(
    f"- {p['label']}: rate {p['interest_rate']}% p.a., tenure {p['min_tenure_years']}-{p['max_tenure_years']} yrs, "
    f"min credit score {p['min_credit_score']}, max FOIR {int(p['max_foir'] * 100)}%"
    for p in RULES["products"].values()
)

SYSTEM_PROMPT = f"""You are "LoanMitra", the loan-eligibility assistant of a retail bank in India.

Your job: find out what the applicant needs, collect the facts required for an eligibility check, run the bank's rules
through your tools, and explain the result in plain language with concrete next steps.

Rules you must follow
- Every verdict comes from the `update_applicant_profile` tool. Never guess eligibility, EMI, or amounts yourself.
  Call the tool as soon as the user shares any detail, even one. If it returns INCOMPLETE, ask for the missing fields
  (at most 2 or 3 per message, in a natural order). Do not ask for things you already know.
- Reply in the language the user writes in: English, Hindi (Devanagari) or Hinglish (romanised Hindi). If the user
  writes in Hindi, answer fully in Hindi. Keep the numbers in Indian format (₹5 L, ₹1.2 Cr).
- When you give a verdict: state it clearly, give the key reasons (from the tool's checks), the EMI, and the
  improvement steps / what-if options from the tool. Mention the document checklist when eligible or conditional.
- Use `what_if` for hypothetical questions ("what if I add my wife as co-applicant", "and for 7 years?").
- This is an indicative soft check, not a sanction letter; say so once at the end of a verdict, briefly.
- Personal data: do not ask for PAN, Aadhaar, phone or account numbers; they are not needed for a soft check.
  If the user shares them they are already masked before reaching you.
- Stay on topic (loan eligibility, documents, EMIs, credit score guidance). Politely decline anything else.
- Be warm and concise: short paragraphs or short bullet lists, no tables, no headings, no markdown bold spam.
  A verdict message should fit on a phone screen.

Bank policy snapshot (the tool holds the full rules):
{POLICY_SUMMARY}
"""


# ------------------------------------------------------------------ GenAI brain
class GenAIAgent:
    def __init__(self) -> None:
        import anthropic  # imported lazily so the app runs without the package configured

        self.provider = provider()
        if self.provider == "openrouter":
            # OpenRouter exposes the Anthropic Messages API, so the same SDK and tool loop work unchanged.
            self.client = anthropic.Anthropic(base_url=OPENROUTER_BASE_URL, api_key=None,
                                              auth_token=os.environ["OPENROUTER_API_KEY"])
        else:
            self.client = anthropic.Anthropic()

    def _create(self, session: Session):
        params = dict(
            model=MODEL,
            max_tokens=2048,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            tools=TOOLS,
            messages=session.history,
            output_config={"effort": EFFORT},
        )
        if self.provider == "openrouter":
            return self.client.messages.create(**params)
        return self.client.beta.messages.create(**params, betas=["server-side-fallback-2026-07-01"], fallbacks="default")

    def respond(self, session: Session, text: str) -> str:
        session.history.append({"role": "user", "content": text})
        tools_used: list[str] = []
        response = None
        for _ in range(MAX_TOOL_ROUNDS + 1):
            response = self._create(session)
            if response.stop_reason == "refusal":
                session.history.append({"role": "assistant", "content": [{"type": "text", "text": "I can only help with loan eligibility questions."}]})
                return "I can only help with loan eligibility questions. Could you tell me about the loan you need?"

            session.history.append({"role": "assistant", "content": response.content})
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason != "tool_use" or not tool_uses:
                break

            results = []
            for tu in tool_uses:
                tools_used.append(tu.name)
                try:
                    if tu.name == "update_applicant_profile":
                        out = tool_update_profile(session, dict(tu.input))
                    elif tu.name == "what_if":
                        out = tool_what_if(session, dict(tu.input).get("changes", {}))
                    elif tu.name == "list_required_documents":
                        out = tool_documents(tu.input.get("loan_type", ""), tu.input.get("employment_type"))
                    else:
                        out = {"error": f"unknown tool {tu.name}"}
                    results.append({"type": "tool_result", "tool_use_id": tu.id, "content": json.dumps(out, ensure_ascii=False)})
                except Exception as exc:  # keep the loop alive; let the model recover
                    results.append({"type": "tool_result", "tool_use_id": tu.id, "content": f"error: {exc}", "is_error": True})
            session.history.append({"role": "user", "content": results})

        texts = [b.text for b in (response.content if response else []) if b.type == "text"]
        reply = "\n".join(t for t in texts if t.strip()).strip()
        if not reply:
            reply = "Could you tell me a little more about the loan you are looking for?"
        return reply


# ------------------------------------------------------------------ deterministic brain
RESET_WORDS = re.compile(r"\b(reset|restart|start over|start again|new application|naya|फिर से|dobara)\b", re.I)
UNKNOWN_WORDS = re.compile(r"\b(unknown|don'?t know|dont know|not sure|pata nahi|nahi pata|पता नहीं|no idea)\b", re.I)


class DeterministicAgent:
    """Slot-filling fallback. Same tools, no LLM."""

    def respond(self, session: Session, text: str) -> str:
        lang = session.lang
        if RESET_WORDS.search(text):
            session.reset()
            session.expected_field = "loan_type"
            return i18n.t(lang, "reset") + i18n.ask_for(lang, "loan_type")

        fields = extract(text, session.expected_field, session.profile.get("loan_type"))
        if session.expected_field in ("credit_score", "co_applicant_credit_score") and UNKNOWN_WORDS.search(text):
            fields[session.expected_field] = "unknown"

        prefix = ""
        if fields:
            result = tool_update_profile(session, fields)
            learned = ", ".join(f"{FIELD_LABELS.get(k, k)}: {self._show(k, v)}" for k, v in fields.items())
            prefix = i18n.t(lang, "noted") + f"({learned})\n"
        elif session.expected_field:
            result = tool_update_profile(session, {})
            prefix = i18n.t(lang, "not_understood")
        else:
            result = tool_update_profile(session, {})

        if result["status"] == "INCOMPLETE":
            nxt = result["missing_fields"][0]
            session.expected_field = nxt
            return prefix + i18n.ask_for(lang, nxt)

        session.expected_field = None
        return prefix + i18n.render_evaluation(lang, result, result.get("documents", []))

    @staticmethod
    def _show(k: str, v: Any) -> str:
        if isinstance(v, bool):
            return "abroad" if v else "India"
        if isinstance(v, (int, float)):
            if k in ("age", "tenure_years", "credit_score", "co_applicant_credit_score", "employment_months"):
                return f"{v:g}"
            return fmt_inr(v)
        return str(v)


# ------------------------------------------------------------------ orchestration
_genai: Optional[GenAIAgent] = None
_det = DeterministicAgent()


def _brain():
    global _genai
    if genai_available():
        if _genai is None:
            _genai = GenAIAgent()
        return _genai, "genai"
    return _det, "deterministic"


def handle_message(session: Session, raw_text: str, lang_pref: str = "auto") -> dict:
    started = time.perf_counter()
    text, pii = mask_pii(raw_text.strip())
    detected = i18n.detect_language(text, lang_pref)
    # Short answers like "5 lakh" or "720" carry no language signal: keep the session's language.
    if lang_pref == "auto" and detected == "en" and len(text.split()) < 4 and session.history is not None:
        detected = session.lang
    session.lang = detected

    brain, mode = _brain()
    try:
        reply = brain.respond(session, text)
    except Exception as exc:  # GenAI failure (network, key, quota) -> degrade gracefully, never crash the demo
        if mode == "genai":
            mode = "deterministic (genai error)"
            reply = _det.respond(session, text)
            reply += f"\n\n[note: GenAI backend unavailable — {type(exc).__name__}]"
        else:
            raise

    latency_ms = int((time.perf_counter() - started) * 1000)
    session.updated = time.time()
    session.transcript.append({"role": "user", "text": text})
    session.transcript.append({"role": "assistant", "text": reply, "latency_ms": latency_ms})
    return {
        "reply": reply,
        "mode": mode,
        "model": MODEL if mode == "genai" else None,
        "language": session.lang,
        "pii_masked": pii,
        "latency_ms": latency_ms,
        "profile": session.profile,
        "missing_fields": [f for f in REQUIRED_FIELDS.get(session.profile.get("loan_type", ""), ["loan_type"]) if session.profile.get(f) is None]
        if session.profile.get("loan_type") else ["loan_type"],
        "evaluation": session.evaluation,
        "documents": required_documents(session.profile["loan_type"], session.profile.get("employment_type")) if session.evaluation else [],
    }
