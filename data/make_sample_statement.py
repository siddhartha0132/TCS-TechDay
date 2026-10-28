"""Generate a SYNTHETIC 6-month bank statement (PDF + CSV) for demoing statement analysis.

    .venv/bin/python -m data.make_sample_statement
Writes frontend/sample_statement.pdf and frontend/sample_statement.csv. Fictional bank, person and employer.
"""
from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

from fpdf import FPDF

OUT = Path(__file__).resolve().parent.parent / "frontend"


def transactions(seed: int = 42) -> list[tuple[date, str, float, float]]:
    r = random.Random(seed)
    rows, bal = [], 48250.00
    start = date(2026, 4, 1)
    for m in range(6):
        month = date(start.year + (start.month - 1 + m) // 12, (start.month - 1 + m) % 12 + 1, 1)
        events = [
            (1, "NEFT CR SALARY ACME TECH PVT LTD", 65000.00),
            (3, "IMPS DR RENT TRANSFER", -16000.00),
            (5, "NACH DR CAR LOAN EMI UDAAN FINANCE", -8500.00),
            (12, "BILLPAY DR ELECTRICITY", -float(r.randint(900, 2200))),
        ]
        for _ in range(r.randint(6, 9)):
            events.append((r.randint(2, 27), r.choice(["UPI DR GROCERY", "UPI DR SWIGGY", "UPI DR PHARMACY", "UPI DR FUEL", "POS DR SHOPPING"]),
                           -float(r.randint(150, 3200))))
        if m == 2:
            events.append((20, "UPI CR REFUND", 1200.00))
        for day, desc, amt in sorted(events):
            bal = round(bal + amt, 2)
            rows.append((month + timedelta(days=day - 1), desc, amt, bal))
    return rows


def main() -> None:
    rows = transactions()
    with open(OUT / "sample_statement.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Narration", "Withdrawal", "Deposit", "Balance"])
        for d, desc, amt, bal in rows:
            w.writerow([d.strftime("%d/%m/%Y"), desc, f"{-amt:.2f}" if amt < 0 else "", f"{amt:.2f}" if amt > 0 else "", f"{bal:.2f}"])

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "Sahyog Public Bank - Account Statement (SYNTHETIC SAMPLE)", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, "Account holder: Demo Applicant   Account: XXXXXXXX1234   Period: 01/04/2026 - 30/09/2026", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, "This statement is fictional and generated for testing LoanMitra.", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.cell(0, 5, "Opening Balance 48,250.00", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 9)
    for head, wdt in (("Date", 24), ("Narration", 80), ("Withdrawal", 28), ("Deposit", 28), ("Balance", 30)):
        pdf.cell(wdt, 6, head, border=1)
    pdf.ln()
    pdf.set_font("Helvetica", "", 8.5)
    for d, desc, amt, bal in rows:
        pdf.cell(24, 5.5, d.strftime("%d/%m/%Y"), border=1)
        pdf.cell(80, 5.5, desc, border=1)
        pdf.cell(28, 5.5, f"{-amt:,.2f}" if amt < 0 else "", border=1, align="R")
        pdf.cell(28, 5.5, f"{amt:,.2f}" if amt > 0 else "", border=1, align="R")
        pdf.cell(30, 5.5, f"{bal:,.2f}", border=1, align="R")
        pdf.ln()
    pdf.output(str(OUT / "sample_statement.pdf"))
    print(f"wrote {len(rows)} transactions -> frontend/sample_statement.pdf, frontend/sample_statement.csv")


if __name__ == "__main__":
    main()
