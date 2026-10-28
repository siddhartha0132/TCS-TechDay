"""Multi-turn conversations against the deterministic agent (no LLM keys)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _setup  # noqa: F401

from backend import agent

assert not agent.genai_available(), "LLM key leaked into env"

VERBOSE = "-v" in sys.argv


def convo(title, turns, show_profile=True):
    print(f"\n######## {title}")
    s = agent.Session()
    out = None
    for t in turns:
        try:
            out = agent.handle_message(s, t)
        except Exception as exc:
            print(f"  USER: {t}\n  !!! CRASH {type(exc).__name__}: {exc}")
            return s, None
        first = out["reply"].split("\n")[0][:150]
        print(f"  USER: {t}\n  BOT : {first}" + (f"\n        {out['reply'][:600]}" if VERBOSE else ""))
    ev = out["evaluation"]
    if show_profile:
        print(f"  => profile={out['profile']}")
    print(f"  => status={ev and ev['status']} eval.loan_type={ev and ev['loan_type']} profile.loan_type={out['profile'].get('loan_type')} "
          f"max={ev and ev['max_eligible_amount']} missing={out['missing_fields']}")
    if ev:
        print(f"  => summary: {ev['summary'][:220]}")
    return s, out


P = ["personal loan", "5 lakh", "3", "30", "60000", "salaried", "760"]

convo("A. Hinglish 'naya' (=new) triggers RESET mid-conversation", [
    "Mujhe home loan chahiye 50 lakh ka 20 saal ke liye", "35", "Naya flat hai, value 70 lakh"])
convo("A2. 'dobara' (=again) in a normal sentence", P + ["0", "Main dobara check karna chahta hoon salary 65000 ke saath"])

convo("B. Personal loan; EMI answer mentions 'home loan' -> loan type silently switches to HOME", P + ["I pay 8000 EMI on my home loan"])
convo("C. Education; co-applicant EMI answer 'car loan' -> switches to AUTO and loan_amount overwritten", [
    "I need an education loan of 10 lakh for 7 years", "22", "India", "my father earns 90k", "his cibil is 760",
    "he pays 12k for a car loan"])

convo("D1. Wrong-field answer: asked credit score, user types income -> score 50,000 accepted -> ELIGIBLE", P[:-1] + ["50k"])
convo("D2. Asked credit score, user says 'not sure, around 680' -> UNKNOWN overrides 680 with 700", P[:-1] + ["not sure, around 680", "0"])
convo("D3. Asked loan amount, user says 'I am 30' -> loan_amount = ₹30", ["personal loan", "I am 30"])
convo("D4. Asked age, user says 'salary 50k' -> age = 50,000", ["personal loan", "5 lakh", "3", "salary 50k"])

convo("E. Income answered '0' -> crash (ZeroDivisionError) in deterministic mode", ["personal loan", "5 lakh", "3", "30", "0"])
convo("E2. Property value answered '0' -> crash", ["home loan", "30 lakh", "20", "35", "90000", "salaried", "760", "0", "0"])

convo("F. Correction after verdict: 'sorry my salary is 80k not 60k' -> loan_amount overwritten to 60k", P + ["0", "sorry my salary is 80k not 60k"])
convo("F2. Correction: 'sorry, I meant 8 lakh'", P + ["0", "sorry, I meant 8 lakh"])
convo("F3. Correction of tenure: 'make it 60 months'", P + ["0", "make it 60 months"])

convo("G. Stale verdict: home ELIGIBLE, then switch to car loan -> evaluation still the old HOME verdict", [
    "home loan 30 lakh for 20 years, property worth 50 lakh, I'm 35, salaried, salary 1 lakh per month, cibil 780, no EMIs",
    "actually I want a car loan instead"])

convo("H. Education -> personal switch: father's income stays and is clubbed into a personal loan", [
    "I need an education loan of 10 lakh for 7 years", "22", "India", "my father earns 2 lakh", "his cibil is 760", "none",
    "actually I need a personal loan of 10 lakh instead", "3", "22", "my salary is 26000", "salaried", "760", "0"])

convo("I. Study location 'India, thanks' -> abroad=True -> ₹1 Cr India course passes amount range", [
    "education loan of 1 crore for 15 years", "24", "India, thanks", "my father earns 3 lakh", "his cibil is 800", "none"])
convo("I2. 'Not abroad, in India'", [
    "education loan of 1 crore for 15 years", "24", "Not abroad, in India", "my father earns 3 lakh", "his cibil is 800", "none"])

convo("J. Annual income read as monthly: '12 lakh per annum' -> eligible for 40 lakh personal loan", [
    "I need a personal loan of 25 lakh for 5 years. My annual income is 12 lakh. I'm 30, salaried, CIBIL 780, no EMIs"])

convo("K. 'unemployed' at employment question -> loops forever", ["personal loan", "5 lakh", "3", "30", "60000", "unemployed", "I am unemployed", "no job"])
convo("K2. 'I lost my job' -> treated as salaried", ["I lost my job, need personal loan 3 lakh for 3 years, 30 years old, 50000 per month, cibil 760, no EMIs"])

convo("L. 'No car loan but 5k credit card EMI' -> existing EMI recorded as 0 and loan type AUTO", P + ["No car loan but 5k credit card EMI"])
convo("M. 'I don't have any EMIs. Salary 80k' in one message -> EMI = 80k", [
    "personal loan of 5 lakh for 3 years, I'm 30, salaried, CIBIL 760", "I don't have any EMIs. Salary 80k"])
convo("N. Experience years taken as tenure", ["I'm 32, salaried with 8 years of experience, salary 70k, need a personal loan of 6 lakh, CIBIL 780, no EMIs"])
convo("O. 'What if 7 years?' after verdict silently overwrites saved profile (and > max tenure)", P + ["0", "what if I take it for 7 years?"])
convo("P. '5-6 lakh' range", ["need personal loan 5-6 lakh for 3 years"])
convo("Q. 'reset' mid flow", P[:3] + ["reset", "car loan"])
convo("R. Wife income + my income in one line (home)", ["home loan 40 lakh for 20 years, flat worth 60 lakh. My wife earns 40k and I earn 60k. I'm 33, salaried, cibil 770, no emi"])

convo("D1b. (completed) credit score answered '50k' -> ELIGIBLE", P[:-1] + ["50k", "0"])
convo("D5. Asked income, user types 'CIBIL 750' -> income ₹750 -> NOT_ELIGIBLE", ["personal loan", "5 lakh", "3", "30", "CIBIL 750", "salaried", "760", "0"])
convo("E1. (completed) income '0' -> crash once all slots are filled", ["personal loan", "5 lakh", "3", "30", "0", "salaried", "760", "0"])
convo("H2. Education -> personal switch, clean answers", [
    "I need an education loan of 10 lakh for 7 years", "22", "India", "my father earns 2 lakh", "his cibil is 760", "none",
    "actually I need a personal loan of 10 lakh instead", "26000", "salaried", "760", "0"])
convo("S. Annual CTC phrasing 'I earn 12 lakh a year'", ["personal loan 10 lakh for 5 years", "30", "I earn 12 lakh a year", "salaried", "780", "0"])

print("\n######## T. GenAI tool path (no LLM call): tool_update_profile with LLM-style strings")
for fields in ({"credit_score": "around 680"}, {"credit_score": "750+"}, {"monthly_income": "50 thousand"},
               {"loan_amount": "2 crores"}, {"loan_amount": "5 lacs"}, {"monthly_income": "Rs 45,000 per month"}):
    s = agent.Session()
    s.profile = {"loan_type": "personal"}
    agent.tool_update_profile(s, fields)
    print(f"  {fields} -> profile {s.profile}")
