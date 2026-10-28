"""Required-document checklists per product and employment type."""
from __future__ import annotations

KYC = ["PAN card", "Aadhaar / passport / voter ID (address proof)", "2 passport-size photographs"]

INCOME = {
    "salaried": ["Last 3 months' salary slips", "Last 6 months' bank statement (salary account)", "Form 16 / ITR for the last 2 years"],
    "self_employed": ["ITR with computation of income for the last 2–3 years", "Last 12 months' bank statement (business + personal)",
                      "Business proof (GST registration / shop & establishment / MOA)", "Audited P&L and balance sheet (if applicable)"],
}

PRODUCT = {
    "personal": [],
    "home": ["Sale agreement / allotment letter", "Title deed and chain of ownership documents", "Approved building plan", "NOC from builder / society", "Property tax receipts"],
    "auto": ["Proforma invoice from the dealer", "Driving licence", "Vehicle quotation with on-road price"],
    "education": ["Admission letter from the institution", "Fee structure / cost of study", "Mark sheets of the last qualifying exam",
                  "Co-applicant's KYC and income documents", "Collateral documents (for loans above ₹7.5 L)", "Passport and visa (for study abroad)"],
}


def required_documents(loan_type: str, employment_type: str | None = None) -> list[str]:
    docs = list(KYC)
    if loan_type == "education":
        docs += PRODUCT["education"]
    else:
        docs += INCOME.get(employment_type or "salaried", INCOME["salaried"])
        docs += PRODUCT.get(loan_type, [])
    return docs
