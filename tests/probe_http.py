"""HTTP hardening, exercised in-process through the real middleware stack (no server, no paid APIs)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["RATE_CHAT_PER_MIN"] = "5"
os.environ["TRUST_PROXY"] = "1"  # distinct clients via X-Forwarded-For (portable across Starlette versions)
import _setup  # noqa: F401,E402

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402

fails = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    fails += not ok
    print(f"{'OK  ' if ok else 'FAIL'} {name} {detail}")


def client(ip: str) -> TestClient:
    return TestClient(app, headers={"X-Forwarded-For": ip})


c = client("10.0.0.1")
r = c.get("/")
check("security headers", all(h in r.headers for h in ("content-security-policy", "x-frame-options", "x-content-type-options")))
check("api docs hidden", c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404)
check("rules endpoint removed", c.get("/api/rules").status_code in (404, 405))
check("simulated API requires consent", c.post("/api/sim/aa/income", json={"consent": False, "mobile_last4": "1234"}).status_code == 422)
check("oversized body -> 413", c.post("/api/chat", json={"message": "a" * 70000}).status_code == 413)
check("unknown field -> 422", c.post("/api/chat", json={"message": "hi", "admin": True}).status_code == 422)
check("bad language -> 422", c.post("/api/chat", json={"message": "hi", "language": "fr"}).status_code == 422)
r = c.post("/api/evaluate", json={"applicant": {"loan_type": "home", "loan_amount": "nan", "tenure_years": 20, "age": 30,
                                               "monthly_income": 0, "employment_type": "salaried", "credit_score": 760,
                                               "existing_emi": 0, "property_value": 0}})
check("garbage numbers -> 200 INCOMPLETE, no crash", r.status_code == 200 and r.json()["status"] == "INCOMPLETE", str(r.status_code))
check("garbage numbers reported", set(r.json().get("invalid_fields", [])) >= {"loan_amount", "property_value"})
r = c.post("/api/chat", json={"message": "my pan is abcde1234f, need personal loan"})
check("verdict withheld until confirmed", c.post("/api/chat", json={"message": "I am 30, salaried, salary 60000, cibil 760, no emi, need 5 lakh personal loan for 3 years"}).json()["evaluation"] is None)
check("PII masked in chat", "PAN" in r.json().get("pii_masked", []))
sid = r.json()["session_id"]
check("session id unguessable", len(sid) >= 32)

c2 = client("10.0.0.2")
codes = [c2.post("/api/chat", json={"message": "hello"}).status_code for _ in range(8)]
check("rate limit per client", codes.count(429) >= 2 and codes[0] == 200, str(codes))
c3 = client("10.0.0.3")
check("other clients unaffected", c3.post("/api/chat", json={"message": "hello"}).status_code == 200)

print(f"http_probe: {fails} failing")
raise SystemExit(1 if fails else 0)
