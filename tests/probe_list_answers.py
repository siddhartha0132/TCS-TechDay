"""List answers: the bot asks for several details and the applicant replies with bare values, one per line.

Regression for a live transcript where "20000 / 5 / 22 / india / 50000 / 600 / none" lost every value but "india"
because the model ran out of time and the fallback couldn't place bare numbers.
"""
import _setup  # noqa: F401  (blanks provider keys, sets the import path)

from backend import agent

fails = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global fails
    fails += not ok
    print(f"{'OK  ' if ok else 'FAIL'} {label} {detail}")


# the reported transcript
s = agent.Session()
agent.handle_message(s, "I want an education loan")
r = agent.handle_message(s, "20000\n5\n22\nindia\n50000\n600\nnone")
want = {"loan_amount": 20000, "tenure_years": 5, "age": 22, "study_abroad": False, "co_applicant_income": 50000,
        "co_applicant_credit_score": 600, "co_applicant_existing_emi": 0}
check("7 values, one per line, all placed", all(r["profile"].get(k) == v for k, v in want.items()), str(r["profile"]))
check("goes straight to confirmation (no verdict yet)", r["pending_confirmation"] and r["evaluation"] is None)

# commas / Indian units / partial lists
s = agent.Session()
agent.handle_message(s, "personal loan")
r = agent.handle_message(s, "5 lakh, 3 years")
check("'5 lakh, 3 years' -> amount + tenure", r["profile"].get("loan_amount") == 500000 and r["profile"].get("tenure_years") == 3, str(r["profile"]))
check("then asks for the next missing detail", r["missing_fields"][:1] == ["age"], str(r["missing_fields"]))

# things that must NOT be treated as a list
P = agent.parse_list_answer
check("Indian number with commas is one value", P("5,00,000", ["loan_amount", "tenure_years"]) is None)
check("sentences go to normal understanding", P("my age is 22, salary 50000", ["age", "monthly_income"]) is None)
check("single value is not a list", P("22", ["age", "monthly_income"]) is None)
check("more values than questions is not a list", P("1\n2\n3", ["age", "monthly_income"]) is None)
check("unreadable value aborts the mapping", P("abc\n5", ["loan_amount", "tenure_years"]) is None)

# after a verdict, list-looking text is not mapped onto old questions
check("no stale questions after confirmation", not s.asked_fields or not s.pending_confirmation)

print(f"list_answers_probe: {fails} failing")
raise SystemExit(1 if fails else 0)
