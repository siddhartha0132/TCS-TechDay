"""Language detection and templated responses (English / Hindi / Hinglish).

Used by the deterministic agent. In GenAI mode the model handles language on
its own and these templates are only a fallback.
"""
from __future__ import annotations

import re

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
HINGLISH_WORDS = {"hai", "hoon", "hu", "mera", "meri", "mujhe", "chahiye", "kya", "kitna", "kitni", "saal", "karod",
                  "nahi", "nahin", "haan", "karna", "batao", "bataye", "ghar", "gaadi", "padhai", "mahine", "paisa", "paise",
                  "naukri", "kaam", "kamata", "kamati", "mein", "aur", "lena", "leni", "liye", "hoga", "hogi", "agar", "toh"}


def detect_language(text: str, preference: str | None = None) -> str:
    """Return 'en' | 'hi' | 'hinglish'. A UI preference other than 'auto' wins."""
    if preference and preference != "auto":
        return preference
    if DEVANAGARI.search(text):
        return "hi"
    words = set(re.findall(r"[a-z]+", text.lower()))
    hits = words & HINGLISH_WORDS
    # One stray word ("aur", "toh") must not flip English to Hinglish: need two hits,
    # or a single hit that dominates a very short message ("kitna?", "chahiye").
    if len(hits) >= 2 or (len(hits) == 1 and len(hits) / max(len(words), 1) >= 0.3):
        return "hinglish"
    return "en"


ASK = {
    "loan_type": {
        "en": "Which loan are you looking for — personal, home, car or education?",
        "hi": "आप कौन सा लोन लेना चाहते हैं — पर्सनल, होम, कार या एजुकेशन?",
        "hinglish": "Aap kaunsa loan lena chahte hain — personal, home, car ya education?",
    },
    "loan_amount": {
        "en": "How much would you like to borrow? (e.g. ₹5 lakh)",
        "hi": "आप कितनी राशि का लोन चाहते हैं? (जैसे ₹5 लाख)",
        "hinglish": "Aapko kitna loan chahiye? (jaise ₹5 lakh)",
    },
    "tenure_years": {
        "en": "Over how many years would you like to repay it?",
        "hi": "आप कितने सालों में लोन चुकाना चाहेंगे?",
        "hinglish": "Kitne saal mein loan chukana chahenge?",
    },
    "age": {"en": "What is your age?", "hi": "आपकी उम्र क्या है?", "hinglish": "Aapki umar kya hai?"},
    "monthly_income": {
        "en": "What is your net monthly income (take-home)?",
        "hi": "आपकी मासिक शुद्ध आय (टेक-होम) कितनी है?",
        "hinglish": "Aapki monthly take-home income kitni hai?",
    },
    "employment_type": {
        "en": "Are you salaried or self-employed?",
        "hi": "आप नौकरीपेशा हैं या स्वरोज़गार (बिज़नेस)?",
        "hinglish": "Aap salaried hain ya self-employed / business?",
    },
    "credit_score": {
        "en": "What is your credit (CIBIL) score? If you don't know, say 'unknown' and I'll continue without it.",
        "hi": "आपका क्रेडिट (CIBIL) स्कोर कितना है? पता न हो तो 'unknown' लिखें, मैं उसके बिना आगे बढ़ूंगा।",
        "hinglish": "Aapka CIBIL score kitna hai? Pata na ho to 'unknown' likhiye, main uske bina aage badhunga.",
    },
    "existing_emi": {
        "en": "How much do you currently pay in EMIs every month? (say 'none' if nothing)",
        "hi": "आप अभी हर महीने कितनी EMI भरते हैं? (कुछ नहीं तो 'नहीं' लिखें)",
        "hinglish": "Abhi aap har mahine kitni EMI bharte hain? (kuch nahi to 'nahi' likhiye)",
    },
    "property_value": {
        "en": "What is the value of the property you plan to buy?",
        "hi": "आप जो संपत्ति खरीदना चाहते हैं उसकी कीमत कितनी है?",
        "hinglish": "Jo property aap kharidna chahte hain uski value kitni hai?",
    },
    "vehicle_price": {
        "en": "What is the on-road price of the vehicle?",
        "hi": "गाड़ी की ऑन-रोड कीमत कितनी है?",
        "hinglish": "Gaadi ki on-road price kitni hai?",
    },
    "study_abroad": {
        "en": "Is the course in India or abroad?",
        "hi": "कोर्स भारत में है या विदेश में?",
        "hinglish": "Course India mein hai ya abroad?",
    },
    "co_applicant_income": {
        "en": "What is your co-applicant's (parent/guardian) net monthly income?",
        "hi": "आपके सह-आवेदक (माता-पिता/अभिभावक) की मासिक आय कितनी है?",
        "hinglish": "Aapke co-applicant (parent/guardian) ki monthly income kitni hai?",
    },
    "co_applicant_credit_score": {
        "en": "What is your co-applicant's credit score? (say 'unknown' to continue without it)",
        "hi": "आपके सह-आवेदक का क्रेडिट स्कोर कितना है? (पता न हो तो 'unknown' लिखें)",
        "hinglish": "Co-applicant ka credit score kitna hai? (pata na ho to 'unknown' likhiye)",
    },
    "co_applicant_existing_emi": {
        "en": "How much does your co-applicant pay in EMIs every month? (say 'none' if nothing)",
        "hi": "आपके सह-आवेदक की मौजूदा EMI कितनी है? (कुछ नहीं तो 'नहीं')",
        "hinglish": "Co-applicant ki existing EMI kitni hai? (kuch nahi to 'nahi')",
    },
}

T = {
    "noted": {"en": "Noted. ", "hi": "ठीक है। ", "hinglish": "Theek hai. "},
    "not_understood": {
        "en": "Sorry, I couldn't pick that up. ",
        "hi": "माफ़ कीजिए, मैं समझ नहीं पाया। ",
        "hinglish": "Sorry, main samajh nahi paya. ",
    },
    "ELIGIBLE": {"en": "✅ Good news — you are eligible.", "hi": "✅ खुशखबरी — आप पात्र हैं।", "hinglish": "✅ Good news — aap eligible hain."},
    "CONDITIONAL": {"en": "🟡 You are conditionally eligible.", "hi": "🟡 आप शर्तों के साथ पात्र हैं।", "hinglish": "🟡 Aap conditionally eligible hain."},
    "NOT_ELIGIBLE": {"en": "🔴 You are not eligible right now.", "hi": "🔴 फ़िलहाल आप पात्र नहीं हैं।", "hinglish": "🔴 Abhi aap eligible nahi hain."},
    "why": {"en": "Why:", "hi": "कारण:", "hinglish": "Kyun:"},
    "next_steps": {"en": "What you can do next:", "hi": "आगे क्या करें:", "hinglish": "Aage kya karein:"},
    "documents": {"en": "Documents to keep ready:", "hi": "ये दस्तावेज़ तैयार रखें:", "hinglish": "Ye documents ready rakhein:"},
    "disclaimer": {
        "en": "This is an indicative soft check — no credit enquiry was made and your score is unaffected. Final approval is subject to document verification.",
        "hi": "यह केवल सांकेतिक जाँच है — कोई क्रेडिट पूछताछ नहीं की गई और आपका स्कोर प्रभावित नहीं हुआ। अंतिम स्वीकृति दस्तावेज़ सत्यापन पर निर्भर है।",
        "hinglish": "Ye sirf indicative soft check hai — koi credit enquiry nahi hui, aapka score affect nahi hua. Final approval documents verify hone ke baad hoga.",
    },
    "ask_more": {
        "en": "You can also ask me 'what if' questions, e.g. “what if I take it for 7 years?”",
        "hi": "आप मुझसे 'क्या होगा अगर' वाले सवाल भी पूछ सकते हैं, जैसे “अगर 7 साल के लिए लूँ तो?”",
        "hinglish": "Aap 'what if' sawaal bhi pooch sakte hain, jaise “7 saal ke liye loon to?”",
    },
    "see_panel": {"en": "Full rule-by-rule breakdown and documents are on the right. Indicative soft check — no CIBIL impact.",
                  "hi": "पूरा विवरण और दस्तावेज़ सूची दाईं ओर है। यह केवल सांकेतिक जाँच है — CIBIL पर कोई असर नहीं।",
                  "hinglish": "Poora breakdown aur documents right side mein hain. Ye sirf indicative check hai — CIBIL pe koi asar nahi."},
    "reset": {"en": "Starting over. ", "hi": "फिर से शुरू करते हैं। ", "hinglish": "Phir se shuru karte hain. "},
    "what_if": {"en": "Here's what would happen if you change that", "hi": "अगर आप यह बदलें तो परिणाम यह होगा",
                "hinglish": "Agar aap ye badlein to result ye hoga"},
    "hypothetical": {"en": "(Hypothetical — your saved details are unchanged.)", "hi": "(यह केवल अनुमान है — आपकी सहेजी गई जानकारी नहीं बदली।)",
                     "hinglish": "(Ye sirf hypothetical hai — aapki saved details nahi badli.)"},
    "invalid": {"en": "That {field} doesn't look right.", "hi": "यह {field} सही नहीं लग रहा।", "hinglish": "Ye {field} sahi nahi lag raha."},
    "estimate_ok": {"en": "An approximate figure is fine, e.g. “about 40k”. ", "hi": "अनुमानित राशि भी चलेगी, जैसे “लगभग 40 हज़ार”। ",
                    "hinglish": "Approx figure bhi chalega, jaise “around 40k”. "},
    "more": {"en": "+{n} more in the side panel.", "hi": "साइड पैनल में +{n} और देखें।",
             "hinglish": "Side panel mein +{n} aur dekhein."},
}


def t(lang: str, key: str) -> str:
    return T[key].get(lang, T[key]["en"])


def ask_for(lang: str, field: str) -> str:
    return ASK.get(field, {}).get(lang) or ASK.get(field, {}).get("en") or f"Please share your {field.replace('_', ' ')}."


def render_evaluation(lang: str, ev: dict, documents: list[str], hypothetical: bool = False) -> str:
    """Short, phone-sized verdict: status, one-line summary, up to 2 reasons and 2 next steps.
    The full rule-by-rule breakdown and the document list are shown in the side panel."""
    if ev["status"] == "INCOMPLETE":
        return ev["summary"]
    lines = [f"{t(lang, ev['status'])} {ev['summary']}"]
    failed = [c for c in ev["checks"] if not c["passed"]]
    if failed:
        lines.append(t(lang, "why"))
        lines += [f"• {c['detail']}" for c in failed[:2]]
        if len(failed) > 2:
            lines.append(t(lang, "more").format(n=len(failed) - 2))
    if ev["improvements"]:
        lines.append(t(lang, "next_steps"))
        lines += [f"• {i}" for i in ev["improvements"][:2]]
        if len(ev["improvements"]) > 2:
            lines.append(t(lang, "more").format(n=len(ev["improvements"]) - 2))
    lines.append(t(lang, "hypothetical") if hypothetical else t(lang, "see_panel"))
    return "\n".join(lines)
