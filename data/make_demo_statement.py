"""Generate the SYNTHETIC demo bank statement used on stage (PDF).

    .venv/bin/python -m data.make_demo_statement
Writes frontend/demo_statement.pdf. Fictional bank, person, employer and account; it reads like a real
statement so the jury sees verification working on a realistic document.

Demo story: the applicant claims "1.2 lakh a month, no EMIs"; the statement shows a salary of 82,000
and two EMIs (6,200 + 3,100), and LoanMitra flags both before giving a verdict.
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

from fpdf import FPDF

OUT = Path(__file__).resolve().parent.parent / "frontend" / "demo_statement.pdf"
OPENING = 52340.00
SALARY = 82000.00
INK, SLATE, GREY, ROW = (17, 21, 33), (72, 72, 96), (120, 120, 144), (240, 242, 246)


def inr(x: float) -> str:
    """Indian digit grouping: 1234567.5 -> 12,34,567.50"""
    whole, frac = f"{abs(x):.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups + [tail]) + "." + frac


def transactions(seed: int = 7) -> list[tuple[date, str, str, float, float]]:
    r = random.Random(seed)
    rows, bal, ref = [], OPENING, 431870
    for m in range(6):
        month = date(2026, 4 + m, 1)
        events = [
            (1, "NEFT CR SALARY NIRMAAN INFOSYSTEMS PVT LTD", SALARY),
            (2, "IMPS DR RENT TO LANDLORD", -21000.00),
            (5, "NACH DR PERSONAL LOAN EMI NOVAEDGE BANK", -6200.00),
            (7, "NACH DR TWO WHEELER LOAN EMI PRAGATI SFB", -3100.00),
            (10, "UPI DR SIP MUTUAL FUND", -5000.00),
            (14, "BILLPAY DR ELECTRICITY BESCOM", -float(r.randint(1100, 2600))),
            (16, "BILLPAY DR MOBILE POSTPAID", -599.00),
            (22, "BILLPAY DR CREDIT CARD", -float(r.randint(6000, 14000))),
        ]
        for _ in range(r.randint(7, 10)):
            events.append((r.randint(2, 27), r.choice([
                "UPI DR GROCERY BIGBASKET", "UPI DR ZOMATO", "UPI DR PHARMACY", "UPI DR PETROL PUMP",
                "POS DR DMART", "UPI DR METRO CARD", "UPI DR SWIGGY INSTAMART"]), -float(r.randint(180, 3400))))
        if m == 2:
            events.append((18, "UPI CR FROM FRIEND", 2500.00))
        if m == 4:
            events.append((26, "IMPS DR FAMILY TRANSFER", -10000.00))
        for day, desc, amt in sorted(events):
            bal = round(bal + amt, 2)
            ref += r.randint(3, 900)
            rows.append((month + timedelta(days=day - 1), desc, f"N{ref}", amt, bal))
    return rows


class Statement(FPDF):
    def header(self) -> None:
        self.set_fill_color(*INK)
        self.rect(0, 0, 210, 22, "F")
        self.set_xy(12, 6)
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", "B", 15)
        self.cell(120, 6, "SAHYOG PUBLIC BANK")
        self.set_font("Helvetica", "", 8)
        self.cell(0, 6, "Statement of Account", align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_x(12)
        self.set_text_color(200, 204, 216)
        self.cell(0, 5, "Koramangala Branch, Bengaluru  |  IFSC SAHY0001234  |  Customer care 1800-000-0000")
        self.set_text_color(*INK)
        self.set_y(28)

    def footer(self) -> None:
        self.set_y(-14)
        self.set_draw_color(*GREY)
        self.line(12, self.get_y(), 198, self.get_y())
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*GREY)
        self.cell(140, 6, "SYNTHETIC DOCUMENT - fictional bank, person and account, generated for the LoanMitra demo. Not a real statement.")
        self.cell(0, 6, f"Page {self.page_no()} of {{nb}}", align="R")


def main() -> None:
    rows = transactions()
    credits = sum(a for *_, a, _ in rows if a > 0)
    debits = -sum(a for *_, a, _ in rows if a < 0)

    pdf = Statement(format="A4")
    pdf.alias_nb_pages()
    pdf.set_margins(12, 12, 12)
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    # account details (left) and summary (right); one value per line so the text stays machine-readable
    left = [("Account holder", "ANANYA VERMA"), ("Account number", "XXXXXXXX4821"), ("Account type", "Savings - Salary"),
            ("Customer ID", "XXXX9073"), ("Currency", "INR")]
    right = [("Statement period", "01/04/2026 - 30/09/2026"), ("Opening balance", inr(OPENING)), ("Total credits", inr(credits)),
             ("Total debits", inr(debits)), ("Closing balance", inr(rows[-1][4]))]
    top = pdf.get_y()
    pdf.set_draw_color(210, 214, 222)
    pdf.rect(12, top, 186, 34)
    for col, items, x in ((0, left, 16), (1, right, 110)):
        pdf.set_y(top + 3)
        for k, v in items:
            pdf.set_x(x)
            pdf.set_font("Helvetica", "", 7.5)
            pdf.set_text_color(*GREY)
            pdf.cell(32, 5.6, k.upper())
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(*INK)
            pdf.cell(50, 5.6, v, new_x="LMARGIN", new_y="NEXT")
    pdf.set_y(top + 38)

    cols = (("Date", 21, "L"), ("Narration", 75, "L"), ("Ref No", 22, "L"), ("Withdrawal", 22, "R"), ("Deposit", 22, "R"), ("Balance", 24, "R"))

    def head() -> None:
        pdf.set_fill_color(*SLATE)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 8)
        for name, w, align in cols:
            pdf.cell(w, 7, name, fill=True, align=align)
        pdf.ln()
        pdf.set_text_color(*INK)

    head()
    pdf.set_font("Helvetica", "", 8)
    for i, (d, desc, ref, amt, bal) in enumerate(rows):
        if pdf.get_y() > 270:
            pdf.add_page()
            head()
            pdf.set_font("Helvetica", "", 8)
        pdf.set_fill_color(*(ROW if i % 2 else (255, 255, 255)))
        vals = (d.strftime("%d/%m/%Y"), desc, ref, inr(-amt) if amt < 0 else "", inr(amt) if amt > 0 else "", inr(bal))
        for (name, w, align), v in zip(cols, vals):
            pdf.cell(w, 6, v, fill=True, align=align)
        pdf.ln()

    pdf.ln(4)
    pdf.set_font("Helvetica", "", 7.5)
    pdf.set_text_color(*GREY)
    pdf.multi_cell(0, 4, "This is a computer-generated statement and does not require a signature. "
                         "Please report any discrepancy within 30 days. NACH = National Automated Clearing House mandate.")
    pdf.output(str(OUT))
    print(f"wrote {len(rows)} transactions, {pdf.page_no()} pages -> {OUT.relative_to(OUT.parent.parent)}")


if __name__ == "__main__":
    main()
