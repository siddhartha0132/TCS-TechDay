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
import logging
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

from . import audit, i18n, lenders, voice
from .documents import required_documents
from .extractor import extract
from .numbers import normalize_text, parse_number
from .privacy import mask_pii
from .rules import (CREDIT_UNKNOWN, FIELD_LABELS, NUMERIC_RANGES, PRODUCT_SPECIFIC, REQUIRED_FIELDS, RULES, evaluate,
                    fmt_inr, validate_profile)

load_dotenv()

EFFORT = os.getenv("LLM_EFFORT", "low")  # low keeps replies well under the 15 s target
MAX_TOOL_ROUNDS = 4
MAX_HISTORY_MESSAGES = 40  # ~10 user turns incl. tool round-trips; then the history restarts with the profile
MAX_TRANSCRIPT = 60
LANG_NAMES = {"en": "English", "hi": "Hindi (Devanagari script)", "hinglish": "Hinglish (Hindi written in Roman letters)",
              **{k: "English" for k in ("bn", "ta", "te", "kn", "ml", "mr", "gu", "pa", "od")}}  # regional: translated by Sarvam
log = logging.getLogger("loanmitra.agent")
OPENROUTER_BASE_URL = "https://openrouter.ai/api"


NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
# Free defaults, picked by measurement (tool calling + Hinglish + latency); see docs/ARCHITECTURE.md
OPENROUTER_FREE_DEFAULT = "nvidia/nemotron-3.5-super-vl:free"
OPENROUTER_FREE_FALLBACKS = "nvidia/nemotron-3.5-lightning:free,nvidia/nemotron-3-ultra-550b-a55b:free"
NVIDIA_DEFAULT = "nvidia/nemotron-3-ultra-550b-a55b"
TURN_BUDGET_S = float(os.getenv("LLM_TURN_BUDGET_S", "13"))
SERVER_FALLBACK = os.getenv("ANTHROPIC_SERVER_FALLBACK", "0") == "1"  # leaves headroom under the 15 s target
MIN_CALL_S = 2.0
DEFAULT_CALL_ESTIMATE_S = 6.0


@dataclass(frozen=True)
class Backend:
    kind: str  # anthropic | openrouter (both Anthropic Messages API) | nvidia (OpenAI-compatible)
    model: str


def _openrouter_id(name: str) -> str:
    # Anthropic IDs (claude-opus-5-5) -> OpenRouter IDs (anthropic/claude-opus-5.5)
    return name if "/" in name else "anthropic/" + re.sub(r"-(\d+)-(\d+)$", r"-\1.\2", name)


def backends() -> list[Backend]:
    """Ordered provider chain: paid Claude (if configured) -> free OpenRouter -> free NVIDIA -> more free OpenRouter."""
    chain: list[Backend] = []
    if os.getenv("ANTHROPIC_API_KEY"):
        chain.append(Backend("anthropic", os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5")))
    if os.getenv("OPENROUTER_API_KEY"):
        chain.append(Backend("openrouter", _openrouter_id(os.getenv("OPENROUTER_MODEL", OPENROUTER_FREE_DEFAULT))))
    if os.getenv("NVIDIA_API_KEY"):
        chain.append(Backend("nvidia", os.getenv("NVIDIA_MODEL", NVIDIA_DEFAULT)))
    if os.getenv("OPENROUTER_API_KEY"):
        for m in os.getenv("OPENROUTER_FALLBACK_MODELS", OPENROUTER_FREE_FALLBACKS).split(","):
            if m.strip():
                chain.append(Backend("openrouter", _openrouter_id(m.strip())))
    seen: set[Backend] = set()
    return [b for b in chain if not (b in seen or seen.add(b))]


def genai_available() -> bool:
    return bool(backends())


MODEL = backends()[0].model if backends() else None


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
    last_model: Optional[str] = None
    reply_source: Optional[str] = None  # genai | genai+rules-template | rules
    confirmed_sig: Optional[str] = None  # signature of the profile the applicant confirmed
    pending_confirmation: bool = False
    statement: Optional[dict] = None  # aggregates from an uploaded bank statement (no transactions)
    asked_fields: list[str] = field(default_factory=list)  # details still missing when the bot last replied, in order

    def reset(self) -> None:
        self.profile, self.evaluation, self.expected_field, self.history = {}, None, None, []
        self.confirmed_sig, self.pending_confirmation, self.statement = None, False, None
        self.asked_fields = []


# ------------------------------------------------------------------ tools (shared by both brains)
UNKNOWN_WORDS = re.compile(r"\b(unknown|don'?t know|dont know|not sure|no idea|pata nahi|nahi pata|n/?a)\b|पता नहीं", re.I)


def _mark_unknown_scores(fields: dict[str, Any]) -> dict[str, Any]:
    """'don't know' (with no number in it) -> explicit unknown; 'around 680' keeps the 680."""
    fields = dict(fields)
    for k in ("credit_score", "co_applicant_credit_score"):
        v = fields.get(k)
        if isinstance(v, str) and not re.search(r"\d", v) and UNKNOWN_WORDS.search(v):
            fields[k] = CREDIT_UNKNOWN
    return fields


def _merge(profile: dict[str, Any], clean: dict[str, Any]) -> dict[str, Any]:
    """Merge new facts; switching product drops the old product's specific facts so nothing stale is reused."""
    merged = dict(profile)
    old_type, new_type = profile.get("loan_type"), clean.get("loan_type")
    if old_type and new_type and new_type != old_type:
        for k in PRODUCT_SPECIFIC.get(old_type, set()) | {"loan_amount", "tenure_years"}:
            if k not in clean:
                merged.pop(k, None)
    merged.update(clean)
    return merged


def _range_note(invalid: list[str]) -> str:
    parts = []
    for k in invalid:
        lo, hi = NUMERIC_RANGES.get(k, (None, None))
        rng = f" (expected {lo:g}–{hi:g})" if k in ("credit_score", "co_applicant_credit_score", "age", "tenure_years") else ""
        parts.append(f"{FIELD_LABELS.get(k, k)}{rng}")
    return "Rejected as invalid or out of range, ask again: " + ", ".join(parts)


def _sig(profile: dict[str, Any]) -> str:
    return json.dumps(profile, sort_keys=True, default=str)


def plausibility_warnings(p: dict[str, Any], statement: Optional[dict] = None) -> list[str]:
    """Values that are valid but unusual: likely magnitude or monthly/annual mix-ups worth a second look,
    plus disagreements with the applicant's own bank statement when one was uploaded."""
    w = []
    if statement:
        stated, seen = p.get("monthly_income"), statement.get("avg_monthly_income") or 0
        if isinstance(stated, (int, float)) and seen and abs(stated - seen) > 0.2 * seen:
            w.append(f"You said {fmt_inr(stated)}/month, but your bank statement shows about {fmt_inr(seen)}/month.")
        emi_s, emi_seen = p.get("existing_emi"), statement.get("avg_monthly_emi") or 0
        if isinstance(emi_s, (int, float)) and emi_seen and emi_s + 500 < emi_seen * 0.8:
            w.append(f"Your statement shows EMI payments of about {fmt_inr(emi_seen)}/month.")
        if statement.get("bounced_payments"):
            w.append(f"The statement shows {statement['bounced_payments']} bounced payment(s); lenders check this.")
    inc = p.get("monthly_income") or p.get("co_applicant_income")
    if isinstance(inc, (int, float)):
        if inc > 500000:
            w.append(f"Monthly income {fmt_inr(inc)} is very high — is that per year?")
        elif inc < 8000:
            w.append(f"Monthly income {fmt_inr(inc)} looks low — is that correct?")
    amt = p.get("loan_amount")
    if isinstance(amt, (int, float)) and isinstance(inc, (int, float)) and inc > 0 and p.get("loan_type") != "education" and amt > 120 * inc:
        w.append(f"The loan ({fmt_inr(amt)}) is over 120× your monthly income — please check both figures.")
    emi = p.get("existing_emi")
    if isinstance(emi, (int, float)) and isinstance(p.get("monthly_income"), (int, float)) and emi > p["monthly_income"]:
        w.append("Existing EMIs are higher than your monthly income — please check.")
    asset = p.get("property_value") or p.get("vehicle_price")
    if isinstance(asset, (int, float)) and isinstance(amt, (int, float)) and amt > asset:
        w.append("The loan is larger than the property / vehicle value — please check.")
    return w


REVIEW_ORDER = ["loan_type", "loan_amount", "tenure_years", "age", "employment_type", "employment_months", "monthly_income",
                "credit_score", "existing_emi", "property_value", "vehicle_price", "study_abroad", "co_applicant_income",
                "co_applicant_credit_score", "co_applicant_existing_emi"]


def review_items(p: dict[str, Any]) -> list[dict[str, str]]:
    def label(k: str) -> str:
        text = FIELD_LABELS.get(k, k).split(" (")[0]
        return text[:1].upper() + text[1:]

    def value(k: str, v: Any) -> str:
        shown = DeterministicAgent._show(k, v)
        return {"tenure_years": f"{shown} years", "employment_months": f"{shown} months", "loan_type": f"{shown} loan"}.get(k, shown) \
            .replace("auto loan", "car loan")
    keys = [k for k in REVIEW_ORDER if k in p] + [k for k in p if k not in REVIEW_ORDER]
    return [{"field": k, "label": label(k), "value": value(k, p[k])} for k in keys]


def tool_update_profile(session: Session, fields: dict[str, Any]) -> dict:
    """Merge newly learned facts and re-run the rules engine.

    The verdict is withheld until the applicant confirms the exact values the engine will use
    (status NEEDS_CONFIRMATION); any change to a confirmed profile asks for confirmation again.
    """
    clean, invalid = validate_profile(_mark_unknown_scores(fields))
    session.profile = _merge(session.profile, clean)
    ev = evaluate(session.profile).as_dict()
    if ev["status"] != "INCOMPLETE" and _sig(session.profile) != session.confirmed_sig:
        session.evaluation, session.pending_confirmation = None, True
        out = {"status": "NEEDS_CONFIRMATION", "profile": session.profile, "review": review_items(session.profile),
               "warnings": plausibility_warnings(session.profile, session.statement), "invalid_fields": invalid,
               "instruction": "All details are collected. List these values for the applicant and ask them to reply "
                              "'confirm' or correct anything. Do NOT state any verdict, amount or EMI yet."}
        if invalid:
            out["note"] = _range_note(invalid)
        return out
    session.pending_confirmation = False
    session.evaluation = ev if ev["status"] != "INCOMPLETE" else None  # never show a verdict for an old profile
    out = dict(ev)
    out["profile"] = session.profile
    out["invalid_fields"] = invalid
    if invalid:
        out["note"] = _range_note(invalid)
    if ev["status"] != "INCOMPLETE":
        out["documents"] = required_documents(session.profile.get("loan_type", ""), session.profile.get("employment_type"))
    return out


def confirm_profile(session: Session) -> dict:
    """Applicant confirmed the values on screen: unlock the verdict for exactly this profile."""
    session.confirmed_sig = _sig(session.profile)
    return tool_update_profile(session, {})


def render_confirmation(lang: str, out: dict) -> str:
    lines = [i18n.t(lang, "confirm_intro")]
    lines += [f"• {it['label']}: {it['value']}" for it in out.get("review", [])]
    if out.get("warnings"):
        lines.append(i18n.t(lang, "confirm_warn"))
        lines += [f"• ⚠️ {w}" for w in out["warnings"]]
    lines.append(i18n.t(lang, "confirm_ask"))
    return "\n".join(lines)


def tool_what_if(session: Session, changes: dict[str, Any]) -> dict:
    """Hypothetical re-evaluation without changing the saved profile."""
    if session.evaluation is None:
        return {"status": "NEEDS_CONFIRMATION", "instruction": "Ask the applicant to confirm their details first."}
    clean, invalid = validate_profile(_mark_unknown_scores(changes))
    out = evaluate(_merge(session.profile, clean)).as_dict()
    out["hypothetical_changes"] = clean
    out["note"] = "Hypothetical only; the saved application is unchanged." + (f" {_range_note(invalid)}" if invalid else "")
    return out


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
        "name": "compare_lenders",
        "description": (
            "Compare the applicant's saved profile across the bank's lender panel (different banks / NBFCs with "
            "different interest rates, CIBIL cut-offs and FOIR limits). Returns each lender's verdict, rate, EMI, "
            "maximum amount and processing fee, best option first. Use when the user asks which bank is best, "
            "for the lowest rate, or where else they could get the loan."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
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
  Call the tool as soon as the user shares any detail, even one. If it returns INCOMPLETE, ask for the next missing
  fields in exactly the order of `missing_fields`, at most 2 per message. Do not ask for things you already know.
- Language: every user message ends with a bracketed note such as [Reply in English]. Always reply in exactly
  that language, even if earlier turns used another one. Keep numbers in Indian format (₹5 L, ₹1.2 Cr).
- When you give a verdict: one line with the verdict and the amount / EMI, then at most 2 short reasons (only
  the failed or borderline checks) and at most 2 next steps from the tool. The screen already shows every rule,
  the full plan and the document list, so do not repeat them; mention documents only when asked.
- Use `compare_lenders` when the user asks which bank is best, about interest rates, or where else to apply;
  name the best option and one alternative in a sentence (the screen shows the full table).
- Use `what_if` for hypothetical questions ("what if I add my wife as co-applicant", "and for 7 years?").
- This is an indicative soft check; mention it in a few words only on the first verdict.
- Personal data: do not ask for PAN, Aadhaar, phone or account numbers; they are not needed for a soft check.
  If the user shares them they are already masked before reaching you.
- Stay on topic (loan eligibility, documents, EMIs, credit score guidance). Politely decline anything else.
- Be warm and brief: at most about 60 words per reply, plain sentences or up to 4 short bullets, no tables, no
  headings. When asking for details, ask in one short sentence.

Bank policy snapshot (the tool holds the full rules):
{POLICY_SUMMARY}
"""


# ------------------------------------------------------------------ GenAI brain
def _bget(block: Any, key: str, default: Any = None) -> Any:
    """History blocks are SDK objects (Anthropic-protocol replies) or plain dicts (ours / NVIDIA)."""
    return block.get(key, default) if isinstance(block, dict) else getattr(block, key, default)


_POOL = ThreadPoolExecutor(max_workers=16, thread_name_prefix="llm")


class BackendUnavailable(Exception):
    pass


@dataclass
class LLMReply:
    stop_reason: str
    content: list


class GenAIAgent:
    """Claude-style tool loop over a chain of providers, with a hard per-turn latency budget."""

    def __init__(self) -> None:
        self.chain = backends()
        self._clients: dict[str, Any] = {}
        self._http = httpx.Client(timeout=TURN_BUDGET_S)
        self.call_seconds: dict[str, float] = {}  # EWMA of observed call latency per model (drives the fast path)

    # ---------------- provider calls
    def _anthropic_client(self, kind: str):
        import anthropic  # imported lazily so the app runs without the package configured

        if kind not in self._clients:
            # Retries are handled by our own fallback chain + turn budget, not by SDK backoff.
            if kind == "openrouter":
                # OpenRouter exposes the Anthropic Messages API, so the same SDK and tool loop work unchanged.
                self._clients[kind] = anthropic.Anthropic(base_url=OPENROUTER_BASE_URL, api_key=None, max_retries=0,
                                                          auth_token=os.environ["OPENROUTER_API_KEY"])
            else:
                self._clients[kind] = anthropic.Anthropic(max_retries=0)
        return self._clients[kind]

    def _call_anthropic(self, b: Backend, history: list, timeout: float) -> LLMReply:
        import anthropic

        client = self._anthropic_client(b.kind).with_options(timeout=timeout)
        params = dict(model=b.model, max_tokens=1024, tools=TOOLS, messages=history,
                      system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                      output_config={"effort": EFFORT})
        try:
            if b.kind == "anthropic" and SERVER_FALLBACK:
                # Opt-in: Anthropic server-side refusal fallback (beta). Off by default; our own chain covers failures.
                r = client.beta.messages.create(**params, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
            else:
                r = client.messages.create(**params)
        except (anthropic.APIStatusError, anthropic.APITimeoutError, anthropic.APIConnectionError) as exc:
            raise BackendUnavailable(type(exc).__name__) from exc
        return LLMReply(r.stop_reason, list(r.content))

    def _call_nvidia(self, b: Backend, history: list, timeout: float) -> LLMReply:
        body = {"model": b.model, "max_tokens": 1024, "temperature": 0.3, "tool_choice": "auto",
                "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + _to_openai(history),
                "tools": [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                            "parameters": t["input_schema"]}} for t in TOOLS],
                "chat_template_kwargs": {"enable_thinking": False}}
        try:
            r = self._http.post(NVIDIA_URL, json=body, timeout=timeout,
                                headers={"Authorization": f"Bearer {os.environ['NVIDIA_API_KEY']}"})
        except httpx.HTTPError as exc:
            raise BackendUnavailable(type(exc).__name__) from exc
        if r.status_code != 200:
            raise BackendUnavailable(f"HTTP {r.status_code}")
        msg = r.json()["choices"][0]["message"]
        content: list[dict] = []
        if (msg.get("content") or "").strip():
            content.append({"type": "text", "text": msg["content"]})
        for tc in msg.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                continue  # malformed call: drop it; the model gets another chance next round
            content.append({"type": "tool_use", "id": re.sub(r"[^A-Za-z0-9_-]", "_", tc.get("id") or uuid.uuid4().hex),
                            "name": tc["function"]["name"], "input": args if isinstance(args, dict) else {}})
        stop = "tool_use" if any(c["type"] == "tool_use" for c in content) else "end_turn"
        return LLMReply(stop, content)

    def _call(self, chain: list[Backend], session: Session, deadline: float) -> tuple[LLMReply, Backend]:
        """First backend in the chain that answers inside the budget. TimeoutError hands the turn to the rules agent."""
        for b in chain:
            remaining = deadline - time.perf_counter()
            if remaining < MIN_CALL_S:
                break
            started = time.perf_counter()
            fn = self._call_nvidia if b.kind == "nvidia" else self._call_anthropic
            # Hard wall-clock deadline: providers that stream keep-alive bytes never trip an HTTP read timeout,
            # so wait on a worker thread and abandon the call (it finishes in the background) when time is up.
            future = _POOL.submit(fn, b, list(session.history), remaining)
            try:
                reply = future.result(timeout=remaining)
            except FuturesTimeout:
                log.warning("backend %s/%s exceeded the turn budget; trying next", b.kind, b.model)
                continue
            except BackendUnavailable as exc:
                log.warning("backend %s/%s unavailable (%s); trying next", b.kind, b.model, exc)
                continue
            took = time.perf_counter() - started
            prev = self.call_seconds.get(b.model, took)
            self.call_seconds[b.model] = 0.7 * prev + 0.3 * took
            return reply, b
        raise TimeoutError("LLM turn budget exhausted")

    # ---------------- the loop
    def respond(self, session: Session, text: str) -> str:
        deadline = time.perf_counter() + TURN_BUDGET_S
        chain = list(self.chain)
        if len(session.history) >= MAX_HISTORY_MESSAGES:
            # Bound tokens/cost per session: start a fresh conversation carrying only the facts.
            # (A new conversation, not an edit of the old one, so thinking blocks stay valid.)
            session.history = []
        if not session.history and session.profile:
            # Fresh LLM history (cap reached, or an earlier turn fell back to the rules agent): carry the facts over.
            text = (f"[Context carried over from earlier in this chat — facts already collected: "
                    f"{json.dumps(session.profile, ensure_ascii=False)}]\n\n{text}")
        session.history.append({"role": "user", "content": text})
        reply = None
        last_tool: Optional[tuple[str, dict]] = None
        confirm_card: Optional[dict] = None
        for _ in range(MAX_TOOL_ROUNDS + 1):
            # Fast path: the facts are already processed by the rules engine; if the model can't explain them
            # inside the budget, render the engine's own explanation instead of blowing the 15 s target.
            if last_tool and deadline - time.perf_counter() < self.call_seconds.get(chain[0].model, DEFAULT_CALL_ESTIMATE_S) * 1.2:
                text_reply = self._render(session, *last_tool)
                session.history.append({"role": "assistant", "content": [{"type": "text", "text": text_reply}]})
                session.reply_source = "genai+rules-template"
                return text_reply

            reply, used = self._call(chain, session, deadline)
            chain = [used] + [b for b in chain if b != used]  # stay on the backend that answered this turn
            session.last_model = used.model
            if reply.stop_reason == "refusal":
                session.history.append({"role": "assistant", "content": [{"type": "text", "text": "I can only help with loan eligibility questions."}]})
                return "I can only help with loan eligibility questions. Could you tell me about the loan you need?"

            session.history.append({"role": "assistant", "content": reply.content})
            tool_uses = [b for b in reply.content if _bget(b, "type") == "tool_use"]
            if reply.stop_reason != "tool_use" or not tool_uses:
                break

            results = []
            for tu in tool_uses:
                name, args, tid = _bget(tu, "name"), dict(_bget(tu, "input") or {}), _bget(tu, "id")
                try:
                    if name == "update_applicant_profile":
                        out = tool_update_profile(session, args)
                    elif name == "what_if":
                        out = tool_what_if(session, args.get("changes") or {})
                    elif name == "compare_lenders":
                        out = lenders.compare(session.profile) if session.evaluation else \
                            {"status": "NEEDS_CONFIRMATION", "instruction": "Ask the applicant to confirm their details first."}
                    elif name == "list_required_documents":
                        out = tool_documents(args.get("loan_type", ""), args.get("employment_type"))
                    else:
                        out = {"error": f"unknown tool {name}"}
                    last_tool = (name, out)
                    if out.get("status") == "NEEDS_CONFIRMATION" and name == "update_applicant_profile" and out.get("review"):
                        confirm_card = out
                    results.append({"type": "tool_result", "tool_use_id": tid, "content": json.dumps(out, ensure_ascii=False)})
                except Exception as exc:  # keep the loop alive; let the model recover
                    log.exception("tool %s failed", name)
                    results.append({"type": "tool_result", "tool_use_id": tid, "content": f"error: {type(exc).__name__}", "is_error": True})
            session.history.append({"role": "user", "content": results})
            if confirm_card:
                text_reply = render_confirmation(session.lang, confirm_card)
                session.history.append({"role": "assistant", "content": [{"type": "text", "text": text_reply}]})
                session.reply_source = "genai+rules-template"
                return text_reply

        texts = [_bget(b, "text") for b in (reply.content if reply else []) if _bget(b, "type") == "text"]
        out_text = "\n".join(t for t in texts if t and t.strip()).strip()
        session.reply_source = "genai"
        return out_text or "Could you tell me a little more about the loan you are looking for?"

    @staticmethod
    def _render(session: Session, tool: str, out: dict) -> str:
        lang = session.lang
        if tool == "compare_lenders":
            return lenders.compare_text(out)
        if tool == "list_required_documents":
            return i18n.t(lang, "documents") + "\n" + "\n".join(f"• {d}" for d in out.get("documents", []))
        if out.get("status") == "NEEDS_CONFIRMATION":
            return render_confirmation(lang, out) if out.get("review") else i18n.t(lang, "confirm_ask")
        if out.get("status") == "INCOMPLETE":
            missing = out.get("missing_fields") or ["loan_type"]
            return " ".join(i18n.ask_for(lang, f) for f in missing[:2])
        return i18n.render_evaluation(lang, out, out.get("documents", []), hypothetical=tool == "what_if")


def _to_openai(history: list) -> list[dict]:
    """Anthropic-format history (SDK objects or dicts) -> OpenAI chat messages. Thinking blocks are dropped."""
    msgs: list[dict] = []
    for m in history:
        role, content = m["role"], m["content"]
        if isinstance(content, str):
            msgs.append({"role": role, "content": content})
            continue
        if role == "assistant":
            text = "".join(_bget(b, "text") or "" for b in content if _bget(b, "type") == "text")
            calls = [{"id": _bget(b, "id"), "type": "function",
                      "function": {"name": _bget(b, "name"), "arguments": json.dumps(_bget(b, "input") or {}, ensure_ascii=False)}}
                     for b in content if _bget(b, "type") == "tool_use"]
            msg: dict[str, Any] = {"role": "assistant", "content": text or None}
            if calls:
                msg["tool_calls"] = calls
            msgs.append(msg)
        else:
            for b in content:
                if _bget(b, "type") == "tool_result":
                    msgs.append({"role": "tool", "tool_call_id": _bget(b, "tool_use_id"), "content": str(_bget(b, "content"))})
                elif _bget(b, "type") == "text":
                    msgs.append({"role": "user", "content": _bget(b, "text")})
    return msgs


# ------------------------------------------------------------------ deterministic brain
# Only a standalone command resets ("naya flat hai" or "dobara check karo" must not wipe the application)
CONFIRM_RE = re.compile(r"^\s*(?:✅\s*)?(?:yes|yeah|yep|y|ok|okay|confirm(?:ed)?|correct|right|all good|looks good|that'?s right|"
                        r"haan|ha|ji|ji haan|sahi|sahi hai|theek hai|thik hai|हाँ|हां|सही|सही है|ठीक है)\b[\w\s,.!'’-]{0,40}$", re.I)
RESET_CMD = re.compile(r"^\s*(?:please\s+)?(?:reset|restart|start over|start again|new application|naya application|"
                       r"phir se shuru(?:\s+kar(?:o|ein|en))?|dobara shuru(?:\s+kar(?:o|ein|en))?|फिर से शुरू(?:\s+कर(?:ें|ो))?)\s*[.!]*\s*$", re.I)
WHAT_IF = re.compile(r"^\s*(?:what if|and if|if i|if my|suppose|agar|kya hoga agar)\b|^\s*अगर", re.I)
COMPARE = re.compile(r"\b(?:compare|comparison|which bank|best bank|other banks?|lenders?|lowest rate|cheapest|kaunsa bank|konsa bank|sabse sasta)\b|कौन सा बैंक|बैंक", re.I)
MONEY_FIELDS = {"monthly_income", "existing_emi", "co_applicant_income", "co_applicant_existing_emi"}


# ------------------------------------------------------------------ list answers
# When the bot asked for several details and the applicant replies with a list of bare values ("20000 / 5 / 22 /
# india / 50000 / 600 / none"), map them in order to the details that were still missing. Deterministic and instant,
# so it works even when the model is slow; the confirmation card then shows every value with its label, so a value
# in the wrong place is caught by the applicant before any verdict.
LIST_SPLIT = re.compile(r"\n+|;|,(?=\s)|\s+/\s+")
VALUE_WORDS = re.compile(
    r"₹|\brs\.?|\binr\b|\b(?:lakhs?|lacs?|laakh|crores?|cr|thousand|hazaa?r|k|l|lpa|years?|yrs?|saal|per month|a month|"
    r"monthly|pm|india|indian|domestic|abroad|foreign|overseas|none|no|nil|zero|nahi|nahin|salaried|self[- ]employed|"
    r"business|not working|unemployed|don'?t know|dont know|unknown|not sure|pata)\b|लाख|करोड़|हज़ार|हजार|भारत|विदेश|नहीं|कोई|पता|साल",
    re.I)
ABROAD = re.compile(r"\b(?:abroad|foreign|overseas|usa|uk|canada|australia|germany)\b|विदेश", re.I)
IN_INDIA = re.compile(r"\b(?:india|indian|domestic)\b|भारत|इंडिया", re.I)
NONE_WORDS = re.compile(r"^\s*(?:no|none|nil|zero|nahi|nahin|no emis?)\s*$|नहीं|कोई नहीं", re.I)


def _list_value(f: str, part: str) -> Any:
    if f == "study_abroad":
        return True if ABROAD.search(part) else False if IN_INDIA.search(part) else None
    if f == "employment_type":
        low = part.lower()
        return ("self_employed" if re.search(r"self|business", low) else "not_employed" if re.search(r"not working|unemployed", low)
                else "salaried" if "salaried" in low else None)
    if f in ("existing_emi", "co_applicant_existing_emi") and NONE_WORDS.search(part):
        return 0.0
    if f in ("credit_score", "co_applicant_credit_score") and UNKNOWN_WORDS.search(part) and not re.search(r"\d", part):
        return CREDIT_UNKNOWN
    if f == "loan_type":
        return None
    return parse_number(normalize_text(part))


def parse_list_answer(text: str, asked: list[str]) -> Optional[dict[str, Any]]:
    """{field: value} when `text` is a list of bare values answering `asked` in order, else None."""
    if len(asked) < 2:
        return None
    parts = [p.strip(" .") for p in LIST_SPLIT.split(text) if p and p.strip(" .")]
    if not 2 <= len(parts) <= len(asked):
        return None
    if any(re.search(r"[A-Za-z\u0900-\u097F]", VALUE_WORDS.sub(" ", p)) for p in parts):
        return None  # a part carries its own words ("my age is 22"): let the normal understanding handle it
    out: dict[str, Any] = {}
    for f, part in zip(asked, parts):
        v = _list_value(f, part)
        if v is None:
            return None
        out[f] = v
    return out


class DeterministicAgent:
    """Slot-filling fallback. Same tools, no LLM."""

    def respond(self, session: Session, text: str) -> str:
        lang = session.lang
        if RESET_CMD.match(text):
            session.reset()
            session.expected_field = "loan_type"
            return i18n.t(lang, "reset") + i18n.ask_for(lang, "loan_type")

        loan_type = session.profile.get("loan_type")
        if session.evaluation and WHAT_IF.search(text):
            changes = extract(text, None, loan_type)
            if changes:
                ev = tool_what_if(session, changes)
                shown = ", ".join(f"{FIELD_LABELS.get(k, k)}: {self._show(k, v)}" for k, v in ev["hypothetical_changes"].items())
                return f"{i18n.t(lang, 'what_if')} ({shown})\n" + i18n.render_evaluation(lang, ev, [], hypothetical=True)

        if session.evaluation and COMPARE.search(text):
            return lenders.compare_text(lenders.compare(session.profile))

        fields = extract(text, session.expected_field, loan_type)
        asked = session.expected_field
        if asked in ("credit_score", "co_applicant_credit_score") and asked not in fields and UNKNOWN_WORDS.search(text) \
                and not re.search(r"\d", text):
            fields[asked] = CREDIT_UNKNOWN
        return self.apply_fields(session, fields, text, asked)

    def apply_fields(self, session: Session, fields: dict[str, Any], text: str, asked: Optional[str] = None) -> str:
        """Merge facts, then ask for the next detail, ask for confirmation, or explain the verdict."""
        lang = session.lang
        prefix = ""
        if fields:
            result = tool_update_profile(session, fields)
            accepted = {k: v for k, v in fields.items() if k not in result["invalid_fields"]}
            if accepted and len(accepted) <= 3:
                learned = ", ".join(f"{FIELD_LABELS.get(k, k)}: {self._show(k, v)}" for k, v in accepted.items())
                prefix = i18n.t(lang, "noted") + f"({learned})\n"
            elif accepted:
                prefix = i18n.t(lang, "noted")
            if result["invalid_fields"]:
                bad = result["invalid_fields"][0]
                session.expected_field = bad
                return prefix + i18n.t(lang, "invalid").format(field=FIELD_LABELS.get(bad, bad)) + " " + i18n.ask_for(lang, bad)
        else:
            result = tool_update_profile(session, {})
            if asked:
                hint = i18n.t(lang, "estimate_ok") if asked in MONEY_FIELDS and UNKNOWN_WORDS.search(text) else ""
                prefix = i18n.t(lang, "not_understood") + hint

        if result["status"] == "INCOMPLETE":
            nxt = result["missing_fields"][0]
            session.expected_field = nxt
            return prefix + i18n.ask_for(lang, nxt)
        if result["status"] == "NEEDS_CONFIRMATION":
            session.expected_field = None
            return render_confirmation(lang, result)

        session.expected_field = None
        # The details panel already lists every fact; only echo short updates (e.g. a single correction).
        if len(fields) > 2:
            prefix = ""
        return prefix + i18n.render_evaluation(lang, result, result.get("documents", []))

    @staticmethod
    def _show(k: str, v: Any) -> str:
        if v == CREDIT_UNKNOWN:
            return "not known"
        if k == "employment_type":
            return {"salaried": "salaried", "self_employed": "self-employed", "not_employed": "not employed"}.get(v, str(v))
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
    if lang_pref == "auto" and detected == "en" and len(text.split()) < 4:
        detected = session.lang
    session.lang = detected

    # Regional languages: translate in -> run the same agent in English -> translate the reply back (Sarvam).
    # English, Hindi and Hinglish are handled natively. PII is already masked before anything leaves the server.
    user_lang, translated = session.lang, False
    if user_lang in i18n.TRANSLATED_LANGS and voice.available():
        try:
            text = voice.translate(text, user_lang, "en")
            session.lang, translated = "en", True
        except Exception:
            log.warning("translation into English failed; continuing with the original text")

    before = (session.evaluation or {}).get("status"), (session.evaluation or {}).get("summary")
    session.last_model = None
    session.reply_source = "rules"
    brain, mode = _brain()
    if session.pending_confirmation and CONFIRM_RE.match(text) and not re.search(r"\d", text):
        result = confirm_profile(session)
        reply = i18n.render_evaluation(session.lang, result, result.get("documents", []))
        if session.history and session.history[-1]["role"] == "assistant":
            session.history.append({"role": "user", "content": "I confirm these details are correct."})
            session.history.append({"role": "assistant", "content": [{"type": "text", "text": reply}]})
        session.reply_source = "rules"
    else:
        reply = None
        listed = None if session.evaluation or session.pending_confirmation else parse_list_answer(text, session.asked_fields)
        if listed:
            reply = _det.apply_fields(session, listed, text)
            if session.history and session.history[-1]["role"] == "assistant":
                shown = "; ".join(f"{FIELD_LABELS.get(k, k)} = {DeterministicAgent._show(k, v)}" for k, v in listed.items())
                session.history.append({"role": "user", "content": f"{text}\n[Read in order as: {shown}]"})
                session.history.append({"role": "assistant", "content": [{"type": "text", "text": reply}]})
            session.reply_source = "rules"
    try:
        if reply is None:
            # Explicit per-turn language instruction: free models otherwise drift into Hindi after any Hindi turn.
            reply = brain.respond(session, f"{text}\n\n[Reply in {LANG_NAMES[session.lang]}]" if mode == "genai" else text)
    except Exception as exc:  # GenAI failure (network, key, quota, budget) -> degrade gracefully, never crash the demo
        if mode != "genai":
            raise
        if isinstance(exc, TimeoutError):
            log.warning("GenAI turn over budget; answering with the deterministic agent")
        else:
            log.exception("GenAI turn failed; answering with the deterministic agent")
        # The failed turn may have left a dangling user/tool_use message: start the LLM history afresh.
        session.history = []
        mode = "deterministic (genai error)"
        reply = _det.respond(session, text)

    if translated:
        session.lang = user_lang
        try:
            reply = voice.translate(reply, "en", user_lang)
        except Exception:
            log.warning("translation of the reply failed; answering in English")

    latency_ms = int((time.perf_counter() - started) * 1000)
    session.updated = time.time()
    session.transcript.append({"role": "user", "text": text})
    session.transcript.append({"role": "assistant", "text": reply, "latency_ms": latency_ms})
    del session.transcript[:-MAX_TRANSCRIPT]
    ev = session.evaluation
    missing = [f for f in REQUIRED_FIELDS.get(session.profile.get("loan_type", ""), ["loan_type"]) if session.profile.get(f) is None] \
        if session.profile.get("loan_type") else ["loan_type"]
    session.asked_fields = [] if ev or session.pending_confirmation else missing
    # Engine-authored verdict for this turn. The UI pins it to the bubble so model text
    # (which a prompt injection could steer) can never be the only statement of the decision.
    verified = ({"status": ev["status"], "summary": ev["summary"]}
                if ev and (ev["status"], ev["summary"]) != before else None)
    if verified or session.pending_confirmation:
        audit.record("verdict" if verified else "awaiting_confirmation", session.id,
                     loan_type=session.profile.get("loan_type"), status=verified["status"] if verified else None,
                     mode=mode, source=session.reply_source, language=session.lang, latency_ms=latency_ms,
                     pii_masked=len(pii), warnings=len(plausibility_warnings(session.profile, session.statement)))
    return {
        "reply": reply,
        "verified_verdict": verified,
        "pending_confirmation": session.pending_confirmation,
        "review": review_items(session.profile) if session.pending_confirmation else None,
        "warnings": plausibility_warnings(session.profile, session.statement) if session.pending_confirmation else [],
        "reply_source": session.reply_source if mode == "genai" else "rules",
        "mode": mode,
        "model": (session.last_model or MODEL) if mode == "genai" else None,
        "language": session.lang,
        "pii_masked": pii,
        "latency_ms": latency_ms,
        "profile": session.profile,
        "missing_fields": missing,
        "evaluation": session.evaluation,
        "next_field": None if session.evaluation else (
            next((f for f in REQUIRED_FIELDS.get(session.profile.get("loan_type", ""), []) if session.profile.get(f) is None), None)
            if session.profile.get("loan_type") else "loan_type"),
        "documents": required_documents(session.profile["loan_type"], session.profile.get("employment_type")) if session.evaluation else [],
    }
