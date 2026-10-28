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

from . import i18n
from .documents import required_documents
from .extractor import extract
from .privacy import mask_pii
from .rules import (CREDIT_UNKNOWN, FIELD_LABELS, NUMERIC_RANGES, PRODUCT_SPECIFIC, REQUIRED_FIELDS, RULES, evaluate,
                    fmt_inr, validate_profile)

load_dotenv()

EFFORT = os.getenv("LLM_EFFORT", "low")  # low keeps replies well under the 15 s target
MAX_TOOL_ROUNDS = 4
MAX_HISTORY_MESSAGES = 40  # ~10 user turns incl. tool round-trips; then the history restarts with the profile
MAX_TRANSCRIPT = 60
log = logging.getLogger("loanmitra.agent")
OPENROUTER_BASE_URL = "https://openrouter.ai/api"


NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
# Free defaults, picked by measurement (tool calling + Hinglish + latency); see docs/ARCHITECTURE.md
OPENROUTER_FREE_DEFAULT = "nvidia/nemotron-3.5-super-vl:free"
OPENROUTER_FREE_FALLBACKS = "nvidia/nemotron-3.5-lightning:free,nvidia/nemotron-3-ultra-550b-a55b:free"
NVIDIA_DEFAULT = "nvidia/nemotron-3-ultra-550b-a55b"
TURN_BUDGET_S = float(os.getenv("LLM_TURN_BUDGET_S", "13"))  # leaves headroom under the 15 s target
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

    def reset(self) -> None:
        self.profile, self.evaluation, self.expected_field, self.history = {}, None, None, []


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


def tool_update_profile(session: Session, fields: dict[str, Any]) -> dict:
    """Merge newly learned facts and re-run the rules engine."""
    clean, invalid = validate_profile(_mark_unknown_scores(fields))
    session.profile = _merge(session.profile, clean)
    ev = evaluate(session.profile).as_dict()
    session.evaluation = ev if ev["status"] != "INCOMPLETE" else None  # never show a verdict for an old profile
    out = dict(ev)
    out["profile"] = session.profile
    out["invalid_fields"] = invalid
    if invalid:
        out["note"] = _range_note(invalid)
    if ev["status"] != "INCOMPLETE":
        out["documents"] = required_documents(session.profile.get("loan_type", ""), session.profile.get("employment_type"))
    return out


def tool_what_if(session: Session, changes: dict[str, Any]) -> dict:
    """Hypothetical re-evaluation without changing the saved profile."""
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
        params = dict(model=b.model, max_tokens=2048, tools=TOOLS, messages=history,
                      system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                      output_config={"effort": EFFORT})
        try:
            if b.kind == "openrouter":
                r = client.messages.create(**params)
            else:
                r = client.beta.messages.create(**params, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
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
                    elif name == "list_required_documents":
                        out = tool_documents(args.get("loan_type", ""), args.get("employment_type"))
                    else:
                        out = {"error": f"unknown tool {name}"}
                    last_tool = (name, out)
                    results.append({"type": "tool_result", "tool_use_id": tid, "content": json.dumps(out, ensure_ascii=False)})
                except Exception as exc:  # keep the loop alive; let the model recover
                    log.exception("tool %s failed", name)
                    results.append({"type": "tool_result", "tool_use_id": tid, "content": f"error: {type(exc).__name__}", "is_error": True})
            session.history.append({"role": "user", "content": results})

        texts = [_bget(b, "text") for b in (reply.content if reply else []) if _bget(b, "type") == "text"]
        out_text = "\n".join(t for t in texts if t and t.strip()).strip()
        session.reply_source = "genai"
        return out_text or "Could you tell me a little more about the loan you are looking for?"

    @staticmethod
    def _render(session: Session, tool: str, out: dict) -> str:
        lang = session.lang
        if tool == "list_required_documents":
            return i18n.t(lang, "documents") + "\n" + "\n".join(f"• {d}" for d in out.get("documents", []))
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
RESET_CMD = re.compile(r"^\s*(?:please\s+)?(?:reset|restart|start over|start again|new application|naya application|"
                       r"phir se shuru(?:\s+kar(?:o|ein|en))?|dobara shuru(?:\s+kar(?:o|ein|en))?|फिर से शुरू(?:\s+कर(?:ें|ो))?)\s*[.!]*\s*$", re.I)
WHAT_IF = re.compile(r"^\s*(?:what if|and if|if i|if my|suppose|agar|kya hoga agar)\b|^\s*अगर", re.I)
MONEY_FIELDS = {"monthly_income", "existing_emi", "co_applicant_income", "co_applicant_existing_emi"}


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

        fields = extract(text, session.expected_field, loan_type)
        asked = session.expected_field
        if asked in ("credit_score", "co_applicant_credit_score") and asked not in fields and UNKNOWN_WORDS.search(text) \
                and not re.search(r"\d", text):
            fields[asked] = CREDIT_UNKNOWN

        prefix = ""
        if fields:
            result = tool_update_profile(session, fields)
            accepted = {k: v for k, v in fields.items() if k not in result["invalid_fields"]}
            if accepted:
                learned = ", ".join(f"{FIELD_LABELS.get(k, k)}: {self._show(k, v)}" for k, v in accepted.items())
                prefix = i18n.t(lang, "noted") + f"({learned})\n"
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

        session.expected_field = None
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

    before = (session.evaluation or {}).get("status"), (session.evaluation or {}).get("summary")
    session.last_model = None
    session.reply_source = "rules"
    brain, mode = _brain()
    try:
        reply = brain.respond(session, text)
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

    latency_ms = int((time.perf_counter() - started) * 1000)
    session.updated = time.time()
    session.transcript.append({"role": "user", "text": text})
    session.transcript.append({"role": "assistant", "text": reply, "latency_ms": latency_ms})
    del session.transcript[:-MAX_TRANSCRIPT]
    ev = session.evaluation
    # Engine-authored verdict for this turn. The UI pins it to the bubble so model text
    # (which a prompt injection could steer) can never be the only statement of the decision.
    verified = ({"status": ev["status"], "summary": ev["summary"]}
                if ev and (ev["status"], ev["summary"]) != before else None)
    return {
        "reply": reply,
        "verified_verdict": verified,
        "reply_source": session.reply_source if mode == "genai" else "rules",
        "mode": mode,
        "model": (session.last_model or MODEL) if mode == "genai" else None,
        "language": session.lang,
        "pii_masked": pii,
        "latency_ms": latency_ms,
        "profile": session.profile,
        "missing_fields": [f for f in REQUIRED_FIELDS.get(session.profile.get("loan_type", ""), ["loan_type"]) if session.profile.get(f) is None]
        if session.profile.get("loan_type") else ["loan_type"],
        "evaluation": session.evaluation,
        "next_field": None if session.evaluation else (
            next((f for f in REQUIRED_FIELDS.get(session.profile.get("loan_type", ""), []) if session.profile.get(f) is None), None)
            if session.profile.get("loan_type") else "loan_type"),
        "documents": required_documents(session.profile["loan_type"], session.profile.get("employment_type")) if session.evaluation else [],
    }
