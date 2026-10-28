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


COLLATERAL_THRESHOLD = 750000  # education loans above this need collateral documents

DOCS_HI = {
    "PAN card": "पैन कार्ड",
    "Aadhaar / passport / voter ID (address proof)": "आधार / पासपोर्ट / वोटर ID (पते का प्रमाण)",
    "2 passport-size photographs": "2 पासपोर्ट साइज़ फोटो",
    "Last 3 months' salary slips": "पिछले 3 महीने की सैलरी स्लिप",
    "Last 6 months' bank statement (salary account)": "पिछले 6 महीने का बैंक स्टेटमेंट (सैलरी अकाउंट)",
    "Form 16 / ITR for the last 2 years": "पिछले 2 साल का फॉर्म 16 / ITR",
    "ITR with computation of income for the last 2–3 years": "पिछले 2–3 साल का ITR (आय गणना सहित)",
    "Last 12 months' bank statement (business + personal)": "पिछले 12 महीने का बैंक स्टेटमेंट (बिज़नेस + पर्सनल)",
    "Business proof (GST registration / shop & establishment / MOA)": "बिज़नेस प्रमाण (GST / दुकान पंजीकरण / MOA)",
    "Audited P&L and balance sheet (if applicable)": "ऑडिटेड P&L और बैलेंस शीट (लागू हो तो)",
    "Sale agreement / allotment letter": "सेल एग्रीमेंट / अलॉटमेंट लेटर",
    "Title deed and chain of ownership documents": "टाइटल डीड और स्वामित्व श्रृंखला दस्तावेज़",
    "Approved building plan": "स्वीकृत बिल्डिंग प्लान",
    "NOC from builder / society": "बिल्डर / सोसायटी से NOC",
    "Property tax receipts": "प्रॉपर्टी टैक्स रसीदें",
    "Proforma invoice from the dealer": "डीलर से प्रोफार्मा इनवॉइस",
    "Driving licence": "ड्राइविंग लाइसेंस",
    "Vehicle quotation with on-road price": "ऑन-रोड कीमत सहित गाड़ी का कोटेशन",
    "Admission letter from the institution": "संस्थान से एडमिशन लेटर",
    "Fee structure / cost of study": "फीस संरचना / पढ़ाई की लागत",
    "Mark sheets of the last qualifying exam": "अंतिम योग्यता परीक्षा की मार्कशीट",
    "Co-applicant's KYC and income documents": "सह-आवेदक के KYC और आय दस्तावेज़",
    "Collateral documents (for loans above ₹7.5 L)": "गिरवी दस्तावेज़ (₹7.5 L से ऊपर के लोन हेतु)",
    "Collateral documents": "गिरवी दस्तावेज़",
    "Passport and visa (for study abroad)": "पासपोर्ट और वीज़ा (विदेश पढ़ाई हेतु)",
    "Co-applicant's business proof and ITR (self-employed)": "सह-आवेदक का बिज़नेस प्रमाण और ITR (स्वरोज़गार)",
}


def required_documents(loan_type: str, employment_type: str | None = None, loan_amount: float | None = None,
                       study_abroad: bool | None = None, co_employment_type: str | None = None,
                       lang: str = "en") -> list[str]:
    """Checklist for a product. Amount/location/employment flags prune lines that don't apply;
    when a flag is unknown the conditional line stays with its qualifier."""
    try:
        amt = float(loan_amount) if loan_amount is not None else None
    except (TypeError, ValueError):
        amt = None
    abroad = study_abroad if isinstance(study_abroad, bool) else None
    docs = list(KYC)
    if loan_type == "education":
        docs += [d for d in PRODUCT["education"] if d != "Collateral documents (for loans above ₹7.5 L)"]
        if amt is None:
            docs.append("Collateral documents (for loans above ₹7.5 L)")
        elif amt > COLLATERAL_THRESHOLD:
            docs.append("Collateral documents")
        if abroad is False:
            docs = [d for d in docs if "abroad" not in d]
        if co_employment_type == "self_employed":
            docs.append("Co-applicant's business proof and ITR (self-employed)")
    else:
        docs += INCOME.get(employment_type or "salaried", INCOME["salaried"])
        docs += PRODUCT.get(loan_type, [])
    if lang == "hi":
        docs = [DOCS_HI.get(d, d) for d in docs]
    return docs
