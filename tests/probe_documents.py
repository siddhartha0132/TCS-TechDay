"""Document checklists: conditional lines appear only when they apply; garbage never crashes."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _setup  # noqa: F401,E402

from backend.documents import required_documents  # noqa: E402

fails = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    fails += not ok
    print(f"{'OK  ' if ok else 'FAIL'} {name} {detail}")


def has(docs, frag):
    return any(frag in d for d in docs)


edu_unknown = required_documents("education")
check("education defaults keep qualified collateral", has(edu_unknown, "for loans above"))
check("education defaults keep passport line", has(edu_unknown, "Passport and visa"))
check("education defaults keep KYC", has(edu_unknown, "PAN card"))

edu_small_india = required_documents("education", loan_amount=400000, study_abroad=False)
check("small India loan drops collateral", not has(edu_small_india, "Collateral"))
check("India study drops passport line", not has(edu_small_india, "Passport and visa"))

edu_big_abroad = required_documents("education", loan_amount=4000000, study_abroad=True)
check("big loan keeps firm collateral", has(edu_big_abroad, "Collateral documents") and
      not has(edu_big_abroad, "for loans above"))
check("abroad keeps passport line", has(edu_big_abroad, "Passport and visa"))

edu_self = required_documents("education", co_employment_type="self_employed")
check("self-employed co-applicant adds business proof", has(edu_self, "business proof"))

check("garbage amount keeps qualified line, no crash",
      has(required_documents("education", loan_amount="abc"), "for loans above"))
check("string abroad flag keeps passport line",
      has(required_documents("education", study_abroad="yes"), "Passport and visa"))

sal = required_documents("personal", "salaried")
check("salaried keeps salary slips", has(sal, "salary slips"))
check("salaried has no business proof", not has(sal, "Business proof"))
check("self-employed branch", has(required_documents("home", "self_employed"), "Business proof"))
check("unknown employment falls back to salaried", has(required_documents("auto", "xyz"), "salary slips"))
check("unknown product still returns KYC", has(required_documents("boat", "salaried"), "PAN card"))
check("hindi checklist", has(required_documents("personal", "salaried", lang="hi"), "पैन कार्ड"))
check("hinglish falls back to en", has(required_documents("personal", "salaried", lang="hinglish"), "PAN card"))

print(f"documents_probe: {fails} failing")
raise SystemExit(1 if fails else 0)
