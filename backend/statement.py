"""Bank-statement analysis for income and obligation verification (PDF or CSV), entirely in memory.

Privacy design:
- The file is parsed from bytes in memory and never written to disk.
- Only aggregates leave this module (monthly income, EMI debits, bounces, balance, months covered).
  Narrations, counterparties and account numbers are never returned, logged or sent to an AI model.

Parsing is format-agnostic: each transaction line needs a date and, at its end, the running balance.
Whether a line is a credit or a debit comes from the change in balance, so column order and bank-specific
layouts don't matter. Text-based PDFs only (scanned images would need OCR).
"""
from __future__ import annotations

import csv
import io
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

MAX_PAGES = 30
DATE_PATTERNS = [
    (re.compile(r"\b(\d{2})[/-](\d{2})[/-](\d{4})\b"), "dmy"),
    (re.compile(r"\b(\d{2})[/-](\d{2})[/-](\d{2})\b"), "dmy2"),
    (re.compile(r"\b(\d{1,2})[ -]([A-Za-z]{3})[ -,]*(\d{2,4})\b"), "dMy"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "ymd"),
]
AMOUNT = re.compile(r"(?<![\w.])(?:₹|rs\.?|inr)?\s*(-?\d{1,3}(?:,\d{2,3})*(?:\.\d{1,2})|-?\d+\.\d{1,2})(?:\s*(cr|dr))?\b", re.I)
SALARY = re.compile(r"\b(?:salary|sal|payroll|pay\s?roll|wages|stipend)\b", re.I)
EMI = re.compile(r"\b(?:emi|loan|nach|ach|ecs|e-?mandate|si-|standing instruction|instal+ment|bajaj|finance)\b", re.I)
BOUNCE = re.compile(r"\b(?:return|returned|bounce|insufficient|insuff|chq ret|rtn|dishono(?:u)?r|unpaid)\b", re.I)
SELF_TRANSFER = re.compile(r"\b(?:self|own a/?c|sweep|fd|fixed deposit|rd)\b", re.I)


@dataclass
class Txn:
    day: date
    amount: float  # +credit / -debit
    balance: float
    kind: str  # salary | emi | bounce | transfer | other


def _parse_date(text: str) -> Optional[date]:
    for pat, kind in DATE_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        try:
            if kind == "dmy":
                return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            if kind == "dmy2":
                return date(2000 + int(m.group(3)), int(m.group(2)), int(m.group(1)))
            if kind == "ymd":
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            year = int(m.group(3))
            return datetime.strptime(f"{m.group(1)} {m.group(2)[:3].title()} {year + 2000 if year < 100 else year}", "%d %b %Y").date()
        except ValueError:
            continue
    return None


def _amounts(text: str) -> list[float]:
    out = []
    for m in AMOUNT.finditer(text):
        v = float(m.group(1).replace(",", ""))
        out.append(-abs(v) if (m.group(2) or "").lower() == "dr" else v)
    return out


def _classify(narration: str, amount: float) -> str:
    if BOUNCE.search(narration):
        return "bounce"
    if SELF_TRANSFER.search(narration):
        return "transfer"
    if amount > 0 and SALARY.search(narration):
        return "salary"
    if amount < 0 and EMI.search(narration):
        return "emi"
    return "other"


def _from_lines(lines: list[str]) -> list[Txn]:
    """Each transaction line: a date first and the running balance last. The sign comes from the balance change."""
    txns: list[Txn] = []
    prev_balance: Optional[float] = None
    for line in lines:
        d = _parse_date(line[:40])
        if not d:
            if prev_balance is None and re.search(r"opening balance", line, re.I) and _amounts(line):
                prev_balance = _amounts(line)[-1]
            continue
        nums = _amounts(line)
        if len(nums) < 2:
            if prev_balance is None and nums and re.search(r"opening|b/f|brought forward", line, re.I):
                prev_balance = nums[-1]
            continue
        balance, value = nums[-1], abs(nums[-2])
        if prev_balance is None:
            amount = value if re.search(r"\bcr\b|credit|salary|neft cr|imps cr", line, re.I) else -value
        else:
            delta = round(balance - prev_balance, 2)
            amount = delta if abs(abs(delta) - value) < 1.0 else (value if delta > 0 else -value)
        narration = AMOUNT.sub(" ", line)
        txns.append(Txn(d, amount, balance, _classify(narration, amount)))
        prev_balance = balance
    return txns


def _from_csv(text: str) -> list[Txn]:
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    header = [h.strip().lower() for h in rows[0]]

    def col(*names: str) -> Optional[int]:
        return next((i for i, h in enumerate(header) if any(n in h for n in names)), None)

    i_date, i_desc = col("date"), col("narration", "description", "particular", "details", "remarks")
    i_dr, i_cr, i_bal = col("withdrawal", "debit", "dr"), col("deposit", "credit", "cr"), col("balance")
    if i_date is None or i_bal is None:  # unknown layout: treat rows as text lines
        return _from_lines([" ".join(r) for r in rows])
    txns = []
    for r in rows[1:]:
        if len(r) <= max(x for x in (i_date, i_bal) if x is not None):
            continue
        d = _parse_date(r[i_date])
        bal = _amounts(r[i_bal])
        if not d or not bal:
            continue
        dr = _amounts(r[i_dr]) if i_dr is not None and i_dr < len(r) else []
        cr = _amounts(r[i_cr]) if i_cr is not None and i_cr < len(r) else []
        amount = abs(cr[0]) if cr and cr[0] else -abs(dr[0]) if dr else 0.0
        narration = r[i_desc] if i_desc is not None and i_desc < len(r) else ""
        txns.append(Txn(d, amount, bal[-1], _classify(narration, amount)))
    return txns


def _from_pdf(data: bytes) -> list[Txn]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise ValueError("This PDF is password-protected. Please upload an unlocked statement.")
    lines: list[str] = []
    for page in reader.pages[:MAX_PAGES]:
        lines += (page.extract_text() or "").splitlines()
    return _from_lines(lines)


def analyze(data: bytes, content_type: str) -> dict:
    """Return aggregates only. Raises ValueError with a user-safe message when the file can't be read."""
    is_pdf = data[:5] == b"%PDF-" or "pdf" in content_type
    try:
        txns = _from_pdf(data) if is_pdf else _from_csv(data.decode("utf-8-sig", errors="replace"))
    except ValueError:
        raise
    except Exception:
        raise ValueError("Couldn't read this statement. Please upload a text-based PDF or a CSV export.")
    if len(txns) < 5:
        raise ValueError("Couldn't find enough transactions. Scanned (image) PDFs aren't supported — please upload the bank's PDF or CSV export.")

    months: dict[str, dict[str, float]] = defaultdict(lambda: {"salary": 0.0, "credits": 0.0, "emi": 0.0})
    for t in txns:
        m = months[t.day.strftime("%Y-%m")]
        if t.kind == "salary":
            m["salary"] += t.amount
        if t.amount > 0 and t.kind != "transfer":
            m["credits"] += t.amount
        if t.kind == "emi":
            m["emi"] += -t.amount
    full = sorted(months)
    salaried = sum(1 for k in full if months[k]["salary"] > 0) >= max(2, len(full) // 2)
    basis = [months[k]["salary"] for k in full if months[k]["salary"] > 0] if salaried else [months[k]["credits"] for k in full]
    income = round(statistics.median(basis), -2) if basis else 0.0
    emi_months = [months[k]["emi"] for k in full]
    return {
        "months_covered": len(full),
        "period": f"{full[0]} to {full[-1]}",
        "transactions_read": len(txns),
        "income_type": "salaried" if salaried else "self_employed",
        "avg_monthly_income": income,
        "income_basis": "median monthly salary credits" if salaried else "median monthly credits (no salary pattern found)",
        "avg_monthly_emi": round(statistics.median(emi_months), -2) if emi_months else 0.0,
        "bounced_payments": sum(1 for t in txns if t.kind == "bounce"),
        "avg_balance": round(statistics.mean(t.balance for t in txns), -2),
        "min_balance": round(min(t.balance for t in txns), -2),
        "monthly": [{"month": k, "income": round(months[k]["salary"] if salaried else months[k]["credits"]),
                     "emi": round(months[k]["emi"])} for k in full],
        "privacy": "Analysed in memory; the file was not stored and no transaction details were kept.",
    }
