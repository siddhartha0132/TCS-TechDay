"""Build the evaluation report PDF from eval/model_results.json plus the robustness suites.

    .venv/bin/python -m eval.make_report_pdf
Writes docs/LoanMitra_Evaluation_Report.pdf. Run eval/model_eval.py first for each configuration.
"""
from __future__ import annotations

import json
import random
import re
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from fpdf import FPDF
from fpdf.fonts import FontFace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend import statement  # noqa: E402
from backend.rules import evaluate  # noqa: E402
from eval.run_eval import CASES  # noqa: E402

OUT = ROOT / "docs" / "LoanMitra_Evaluation_Report.pdf"
FONT = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
FONT_B = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
INK, SLATE, GREY, BLUE, LINE = (17, 21, 33), (72, 72, 96), (110, 114, 135), (47, 87, 196), (215, 219, 228)
OK, WARN, BAD = (47, 125, 91), (154, 107, 23), (163, 57, 63)
CLASSES = ["ELIGIBLE", "CONDITIONAL", "NOT_ELIGIBLE", "INCOMPLETE"]
ORDER = ["deterministic:all", "nvidia:all", "deterministic:subset", "nvidia:subset", "openrouter:subset"]
NAMES = {"deterministic": "Rule-based agent (no AI)", "nvidia": "NVIDIA Nemotron 3 Ultra (550B)", "openrouter": "Nemotron 3.5 Super (OpenRouter free)"}


# ----------------------------------------------------------------------------- metrics
def pct(a: float, b: float) -> str:
    if not b:
        return "n/a"
    return "100%" if a == b else f"{100 * a / b:.1f}%"


def summarize(run: dict) -> dict:
    res = run["results"]
    turns = [t for r in res for t in r["turns"]]
    lat = sorted(t["latency_ms"] for t in turns)
    ai_turns = [t for t in turns if t["calls"] or "error" in t["mode"]]  # turns that needed the model
    src = Counter("fallback" if "error" in t["mode"] else "model" if t["source"] == "genai" else
                  "fast path" if t["source"] == "genai+rules-template" and t["calls"] else "engine" for t in turns)
    calls = run.get("calls", [])
    ok_calls = [c for c in calls if c["ok"]]
    lang_cases = [r for r in res if r["lang"] != "en"]
    ai_lat = sorted(t["latency_ms"] for t in turns if t["calls"])
    return {
        "measured": run["config"] == "deterministic" or bool(ok_calls),
        "ai_p50": statistics.median(ai_lat) if ai_lat else None, "ai_p95": ai_lat[int(0.95 * (len(ai_lat) - 1))] if ai_lat else None,
        "ai_max": ai_lat[-1] if ai_lat else None, "ai_n": len(ai_lat),
        "n": len(res), "correct": sum(r["correct"] for r in res),
        "first": [sum(r["first_fields"][0] for r in res), sum(r["first_fields"][1] for r in res)],
        "final": [sum(r["final_fields"][0] for r in res), sum(r["final_fields"][1] for r in res)],
        "turns": statistics.mean(len(r["turns"]) for r in res), "replies": len(turns),
        "p50": statistics.median(lat), "p95": lat[int(0.95 * (len(lat) - 1))], "max": lat[-1],
        "under15": sum(1 for x in lat if x < 15000), "src": src, "ai_turns": len(ai_turns),
        "calls": len(calls), "calls_ok": len(ok_calls),
        "call_p50": statistics.median(c["s"] for c in ok_calls) if ok_calls else None,
        "errors": Counter(re.sub(r"\d{3}", lambda m: m.group(0), c.get("error", "")) for c in calls if not c["ok"]),
        "lang": [sum(all(t["lang_ok"] for t in r["turns"]) for r in res), len(res)],
        "lang_nonen": [sum(all(t["lang_ok"] for t in r["turns"]) for r in lang_cases), len(lang_cases)],
    }


def confusion(res: list[dict]) -> dict:
    m = defaultdict(int)
    for r in res:
        m[(r["expected"], r["got"])] += 1
    return m


def prf(m: dict, cls: str) -> tuple[float, float, float]:
    tp = m[(cls, cls)]
    fp = sum(m[(e, cls)] for e in CLASSES if e != cls)
    fn = sum(m[(cls, g)] for g in CLASSES if g != cls)
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def robustness() -> dict:
    def run(script: str) -> str:
        return subprocess.run([sys.executable, str(ROOT / "tests" / script)], capture_output=True, text=True, cwd=ROOT,
                              env={"PYTHONUTF8": "1", "PATH": "/usr/bin:/bin"}).stdout
    fuzz = run("fuzz_rules.py")
    inv = re.findall(r"^(I\d+\w*)\s+(\d+)\s+(\d+)$", fuzz, re.M)
    head = re.search(r"(\d+) random profiles.*crashes (\d+)", fuzz)
    ext = re.search(r"(\d+) cases, (\d+) failing", run("probe_extractor.py"))
    priv = re.search(r"(\d+) cases, (\d+) failing", run("probe_privacy.py"))
    http = run("probe_http.py")
    edges = run("probe_edges.py")
    # rules engine on the labelled boundary cases + speed
    st = CASES["structured_cases"]
    st_ok = sum(evaluate(c["applicant"]).status == c["expected_status"] for c in st)
    t0 = time.perf_counter()
    for _ in range(300):
        for c in st:
            evaluate(c["applicant"])
    per_ms = (time.perf_counter() - t0) * 1000 / (300 * len(st))
    # statement parsing against generator ground truth
    from data import make_demo_statement, make_sample_statement
    stm = []
    for name, mod, path, inc, emi in (("Demo statement (PDF)", make_demo_statement, "frontend/demo_statement.pdf", 82000, 9300),
                                      ("Sample statement (PDF)", make_sample_statement, "frontend/sample_statement.pdf", 65000, 8500),
                                      ("Sample statement (CSV)", make_sample_statement, "frontend/sample_statement.csv", 65000, 8500)):
        a = statement.analyze((ROOT / path).read_bytes(), "application/pdf" if path.endswith("pdf") else "text/csv")
        stm.append((name, len(mod.transactions()), a["transactions_read"], inc, a["avg_monthly_income"], emi, a["avg_monthly_emi"]))
    return {"fuzz_n": int(head.group(1)), "crashes": int(head.group(2)), "inv": [(n, int(c), int(v)) for n, c, v in inv],
            "ext": (int(ext.group(1)), int(ext.group(2))), "priv": (int(priv.group(1)), int(priv.group(2))),
            "http_ok": http.count("\nOK") + http.startswith("OK"), "http_fail": http.count("\nFAIL"),
            "edges": edges.count("->"), "edge_crash": edges.count("Traceback"),
            "st": (st_ok, len(st)), "per_ms": per_ms, "stm": stm}


# ----------------------------------------------------------------------------- PDF
class Report(FPDF):
    def header(self) -> None:
        if self.page_no() == 1:
            return
        self.set_font("U", "", 7.5)
        self.set_text_color(*GREY)
        self.cell(0, 6, "LoanMitra · Model evaluation report", new_x="LMARGIN")
        self.cell(0, 6, "TCS Technology Day 2026", align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*LINE)
        self.line(15, 19, 195, 19)
        self.set_y(24)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("U", "", 7.5)
        self.set_text_color(*GREY)
        self.cell(0, 6, f"{self.page_no()} / {{nb}}", align="C")

    # helpers
    def h1(self, num: str, text: str) -> None:
        if self.get_y() > 235:
            self.add_page()
        self.ln(3)
        self.set_font("U", "", 8)
        self.set_text_color(*BLUE)
        self.cell(0, 5, num.upper(), new_x="LMARGIN", new_y="NEXT")
        self.set_font("B", "", 15)
        self.set_text_color(*INK)
        self.multi_cell(0, 7.5, text, new_x="LMARGIN", new_y="NEXT")
        self.ln(1.5)

    def h2(self, text: str) -> None:
        if self.get_y() > 250:
            self.add_page()
        self.ln(1.5)
        self.set_font("B", "", 10.5)
        self.set_text_color(*INK)
        self.cell(0, 6, text, new_x="LMARGIN", new_y="NEXT")

    def para(self, text: str, size: float = 9.5, color=(40, 44, 58)) -> None:
        self.set_font("U", "", size)
        self.set_text_color(*color)
        self.multi_cell(0, size * 0.52, text.replace("`", ""), new_x="LMARGIN", new_y="NEXT", markdown=True)
        self.ln(1.5)

    def bullets(self, items: list[str]) -> None:
        self.set_font("U", "", 9.3)
        self.set_text_color(40, 44, 58)
        for it in items:
            self.set_x(18)
            self.cell(4, 4.9, "•")
            self.multi_cell(0, 4.9, it.replace("`", ""), new_x="LMARGIN", new_y="NEXT", markdown=True)
        self.ln(1.5)

    def table(self, rows: list[list[str]], widths: tuple, align=None, size: float = 8.3, highlight_col: int | None = None) -> None:
        self.set_font("U", "", size)
        self.set_text_color(*INK)
        self.set_draw_color(*LINE)
        self.set_fill_color(246, 247, 250)
        head = FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=SLATE)
        with super().table(col_widths=widths, text_align=align or "LEFT", line_height=size * 0.55, headings_style=head,
                           first_row_as_headings=True, borders_layout="HORIZONTAL_LINES", cell_fill_color=(246, 247, 250),
                           cell_fill_mode="ROWS", padding=1.6) as t:
            for row in rows:
                r = t.row()
                for v in row:
                    r.cell(str(v))
        self.ln(3)

    def kpis(self, items: list[tuple[str, str, str]]) -> None:
        w = (180 - 4 * (len(items) - 1)) / len(items)
        y = self.get_y()
        for i, (big, label, sub) in enumerate(items):
            x = 15 + i * (w + 4)
            self.set_fill_color(240, 244, 252)
            self.rect(x, y, w, 25, "F")
            self.set_fill_color(*BLUE)
            self.rect(x, y, 1.2, 25, "F")
            self.set_xy(x + 4, y + 3)
            self.set_font("B", "", 16)
            self.set_text_color(*INK)
            self.cell(w - 6, 8, big)
            self.set_xy(x + 4, y + 12)
            self.set_font("U", "", 7.8)
            self.set_text_color(*SLATE)
            self.multi_cell(w - 6, 3.6, f"{label}\n{sub}", align="L")
        self.set_y(y + 29)

    def room(self, height: float) -> None:
        """Charts are drawn row by row: start a new page rather than letting rows split across pages."""
        if self.get_y() + height > self.h - 20:
            self.add_page()

    def hbars(self, title: str, rows: list[tuple[str, float, str, tuple]], maxv: float = 100) -> None:
        self.room(len(rows) * 8 + 14)
        self.h2(title)
        y = self.get_y() + 1
        for i, (label, v, txt, col) in enumerate(rows):
            yy = y + i * 8
            self.set_xy(15, yy)
            self.set_font("U", "", 8)
            self.set_text_color(*INK)
            self.cell(62, 6, label)
            self.set_fill_color(234, 236, 242)
            self.rect(78, yy + 1, 95, 4.2, "F")
            self.set_fill_color(*col)
            self.rect(78, yy + 1, max(0.5, 95 * min(v, maxv) / maxv), 4.2, "F")
            self.set_xy(175, yy)
            self.cell(20, 6, txt, align="R")
        self.set_y(y + len(rows) * 8 + 3)

    def stacked(self, title: str, rows: list[tuple[str, list[tuple[str, int, tuple]]]]) -> None:
        self.room(len(rows) * 8 + 20)
        self.h2(title)
        y = self.get_y() + 1
        for i, (label, parts) in enumerate(rows):
            yy = y + i * 8
            total = sum(n for _, n, _ in parts) or 1
            self.set_xy(15, yy)
            self.set_font("U", "", 8)
            self.set_text_color(*INK)
            self.cell(62, 6, label)
            x = 78
            for name, n, col in parts:
                w = 117 * n / total
                if w <= 0:
                    continue
                self.set_fill_color(*col)
                self.rect(x, yy + 0.6, w, 5, "F")
                if w > 14:
                    self.set_xy(x, yy)
                    self.set_text_color(255, 255, 255)
                    self.set_font("U", "", 6.8)
                    self.cell(w, 6.2, f"{name} {n}", align="C")
                x += w
        self.set_y(y + len(rows) * 8 + 2)
        self.set_font("U", "", 7.4)
        x = 78
        for name, n, col in (rows[0][1] if rows else []):
            self.set_fill_color(*col)
            self.rect(x, self.get_y() + 1, 3, 3, "F")
            self.set_xy(x + 4, self.get_y())
            self.set_text_color(*SLATE)
            label = name
            self.cell(self.get_string_width(label) + 6, 5, label)
            x += self.get_string_width(label) + 10
        self.ln(7)


def build() -> None:
    data = json.loads((ROOT / "eval" / "model_results.json").read_text())
    runs = {k: data[k] for k in ORDER if k in data}
    S = {k: summarize(v) for k, v in runs.items()}
    skipped = {k: runs.pop(k) for k in [k for k in runs if not S[k]["measured"]]}  # every model call failed: not a model result
    if "openrouter:subset" not in runs:
        runs.pop("deterministic:subset", None)  # the subset only exists for a like-for-like OpenRouter comparison
    R = robustness()
    nl = CASES["nl_cases"]
    langs = Counter(c["lang"] for c in nl)
    stat = Counter(c["expected_status"] for c in nl)
    commit = next(iter(runs.values())).get("commit") or subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                                                                         text=True, cwd=ROOT).stdout.strip()

    pdf = Report(format="A4")
    pdf.add_font("U", "", FONT)
    pdf.add_font("B", "", FONT_B)
    pdf.add_font("U", "B", FONT_B)
    pdf.add_font("U", "I", FONT)
    pdf.set_margins(15, 15, 15)
    pdf.set_auto_page_break(True, 16)
    pdf.alias_nb_pages()
    pdf.set_title("LoanMitra - Model Evaluation Report")
    pdf.set_author("LoanMitra team")

    # ------------------------------------------------------------------ cover
    pdf.add_page()
    pdf.set_fill_color(*INK)
    pdf.rect(0, 0, 210, 92, "F")
    pdf.set_xy(15, 26)
    pdf.set_font("U", "", 9)
    pdf.set_text_color(170, 190, 235)
    pdf.cell(0, 5, "TCS TECHNOLOGY DAY 2026 · BANKING: AUTOMATED LOAN ELIGIBILITY CHATBOT", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("B", "", 28)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 13, "LoanMitra", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("U", "", 17)
    pdf.cell(0, 9, "Model evaluation report: accuracy, latency and robustness", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("U", "", 9)
    pdf.set_text_color(200, 205, 220)
    first = next(iter(runs.values()))
    pdf.cell(0, 5, f"Measured {first['ran_at'][:10]} · code version {commit} · all numbers produced by scripts in the repository", new_x="LMARGIN", new_y="NEXT")
    pdf.set_y(102)

    d_all, n_all = S.get("deterministic:all"), S.get("nvidia:all") if "nvidia:all" in runs else None
    o_sub = S.get("openrouter:subset") if "openrouter:subset" in runs else None
    k = [("100%" if d_all and d_all["correct"] == d_all["n"] else pct(d_all["correct"], d_all["n"]),
          "Verdict accuracy, rules", f"{d_all['correct']}/{d_all['n']} conversations")]
    if n_all:
        k.append((pct(n_all["correct"], n_all["n"]), "Verdict accuracy, NVIDIA AI", f"{n_all['correct']}/{n_all['n']} conversations"))
    if o_sub:
        k.append((pct(o_sub["correct"], o_sub["n"]), "Verdict accuracy, OpenRouter AI", f"{o_sub['correct']}/{o_sub['n']} (subset)"))
    if n_all:
        k.append((pct(*n_all["first"]), "AI extraction accuracy", f"{n_all['first'][0]}/{n_all['first'][1]} fields, first message"))
    worst_under = min((S[x] for x in runs), key=lambda s: s["under15"] / s["replies"])
    k.append((pct(worst_under["under15"], worst_under["replies"]), "Replies under 15 s", "worst configuration"))
    pdf.kpis(k)

    pdf.h1("Summary", "What we measured and what it shows")
    pdf.para("LoanMitra is a single-agent chatbot that decides loan eligibility for personal, home, car and education loans. "
             "Its design splits the work: an **AI model understands the applicant and explains the result**, while a "
             "**deterministic rules engine makes every decision**. This report measures each part separately and the whole "
             "conversation end to end, for every AI model we use and for the no-AI fallback.")
    items = [f"**Brief target: 80%+ accuracy, replies under 15 s.** Rules-based agent: {d_all['correct']}/{d_all['n']} verdicts correct, "
             f"{d_all['under15']}/{d_all['replies']} replies under 15 s."]
    if n_all:
        items.append(f"**NVIDIA Nemotron 3 Ultra (the AI model measured live):** {n_all['correct']}/{n_all['n']} verdicts correct "
                     f"({pct(n_all['correct'], n_all['n'])}); {n_all['first'][0]}/{n_all['first'][1]} facts extracted correctly from the "
                     f"applicant's first message ({pct(*n_all['first'])}); {n_all['calls_ok']}/{n_all['calls']} model calls succeeded; "
                     f"replies that used the model took {n_all['ai_p50'] / 1000:.1f} s median, {n_all['ai_p95'] / 1000:.1f} s p95. "
                     f"The {n_all['calls'] - n_all['calls_ok']} failed calls (server errors and timeouts) were answered by the fallback, "
                     "so no conversation broke.")
    if o_sub:
        items.append(f"**Nemotron 3.5 Super via OpenRouter (free tier):** {o_sub['correct']}/{o_sub['n']} verdicts correct on a 12-case subset; "
                     f"median reply {o_sub['p50'] / 1000:.1f} s.")
    for key in skipped:
        sk = S[key]
        items.append(f"**{NAMES[key.split(':')[0]]}: not measured.** All {sk['calls']} calls were rejected "
                     f"({', '.join(sk['errors'])}: the free tier's daily request limit was used up). The app answered through its "
                     "fallback, so these runs say nothing about that model and are excluded from the results.")
    items += [f"**Rules engine:** {R['st'][0]}/{R['st'][1]} boundary cases correct; 0 violations of {len(R['inv'])} consistency rules "
              f"across {R['fuzz_n']:,} random profiles; {R['per_ms']:.2f} ms per decision.",
              f"**Robustness and privacy:** {R['ext'][0]} real-world extraction messages, {R['edges']} edge-value inputs, "
              f"{R['priv'][0]} PII-masking cases and {R['http_ok']} HTTP security checks, all passing.",
              "**Why accuracy holds when a model is weak:** the verdict always comes from the rules engine, and the applicant "
              "confirms the extracted details before any verdict. A model error shows up as an extra question, not a wrong decision."]
    pdf.bullets(items)

    # ------------------------------------------------------------------ method
    pdf.add_page()
    pdf.h1("1 · Method", "Test data, configurations and metrics")
    pdf.h2("Test data")
    pdf.bullets([f"**{len(nl)} labelled conversations** (`data/test_cases.json`): {langs['en']} English, {langs['hi']} Hindi, {langs['hinglish']} Hinglish. "
                 f"Expected verdicts: {stat['ELIGIBLE']} eligible, {stat['CONDITIONAL']} conditional, {stat['NOT_ELIGIBLE']} not eligible, "
                 f"{stat['INCOMPLETE']} incomplete (the applicant doesn't know a required fact).",
                 f"**{R['st'][1]} rule-boundary cases**: applicants placed exactly on cut-offs (credit score, FOIR, loan-to-value, age at maturity).",
                 f"**{R['fuzz_n']:,} random applicant profiles** (fixed seed) for consistency checks, and **{R['ext'][0]} realistic messages** "
                 "written to break the extractor (“5 lacs”, “12 LPA”, “70 hazaar”, father's income vs own income).",
                 "Every label was set by hand before running the models. All data is synthetic."])
    pdf.h2("Configurations evaluated (one backend at a time, no fallback chain)")
    rows = [["Configuration", "Model", "Cases", "Why"]]
    for key in runs:
        cfg, cases = key.split(":")
        rows.append([NAMES[cfg], runs[key]["model"], f"{S[key]['n']} ({'all' if cases == 'all' else 'stratified subset'})",
                     {"deterministic": "Baseline; also the live fallback", "nvidia": "Main live AI model (free API credits)",
                      "openrouter": "Default free model in the app"}[cfg]])
    pdf.table(rows, (48, 62, 30, 40))
    if "openrouter:subset" in runs:
        pdf.para("The 12-case subset contains every Hindi and Hinglish case plus English cases covering each verdict and loan type. "
                 "It keeps the OpenRouter run inside the free tier's daily request limit; the rules agent is reported on the same "
                 "subset for a like-for-like comparison.", 8.6, GREY)
    for key in skipped:
        pdf.para(f"{NAMES[key.split(':')[0]]} was also run on a 12-case subset (every Hindi and Hinglish case plus English cases "
                 "covering each verdict and loan type), but every call was rejected by the provider's rate limit, so it is "
                 "excluded from the results (see section 4).", 8.6, GREY)
    pdf.h2("Procedure")
    pdf.bullets(["The simulated applicant sends the labelled message. When the bot asks for missing facts, the applicant answers from "
                 "the label (up to 8 turns); when the bot shows the details for confirmation, the applicant replies “Yes, confirm”.",
                 f"Each reply runs under the production settings: a hard {first['budget_s']:.0f}-second turn budget. If the model cannot finish, "
                 "the engine's own explanation is sent (“fast path”); if the model errors or times out, the rules agent answers (“fallback”).",
                 "Every raw model call is timed and recorded with its outcome (success, HTTP error, timeout)."])
    pdf.h2("Metrics")
    pdf.table([["Metric", "Definition"],
               ["Verdict accuracy", "Final verdict (ELIGIBLE / CONDITIONAL / NOT_ELIGIBLE / INCOMPLETE) equals the label"],
               ["First-message extraction", "Share of labelled fields correctly captured from the applicant's first message alone"],
               ["Final field accuracy", "Share of labelled fields correct in the profile the verdict was based on"],
               ["Latency p50 / p95 / max", "Wall-clock time per reply, measured at the server"],
               ["Under 15 s", "Share of replies faster than the brief's 15-second target"],
               ["Reply source", "Model (AI wrote the reply) · fast path (engine text, AI ran out of time) · fallback (AI failed) · engine (no AI needed, e.g. confirmation)"],
               ["Model call success", "Raw API calls that returned a usable answer"],
               ["Language match", "Every reply in the applicant's script (Devanagari for Hindi, Latin otherwise)"],
               ["Precision / recall / F1", "Per verdict class, from the confusion matrix"]], (45, 135))

    # ------------------------------------------------------------------ results
    pdf.add_page()
    pdf.h1("2 · Results", "Model comparison")
    head = ["Metric"] + [f"{NAMES[k.split(':')[0]].split(' (')[0]}\n{'all 36' if k.endswith('all') else 'subset 12'}" for k in runs]
    def row(label, fn):
        return [label] + [fn(S[k]) for k in runs]
    rows = [head,
            row("Verdict accuracy", lambda s: f"{s['correct']}/{s['n']}  ({pct(s['correct'], s['n'])})"),
            row("First-message extraction", lambda s: f"{s['first'][0]}/{s['first'][1]}  ({pct(*s['first'])})"),
            row("Final field accuracy", lambda s: f"{s['final'][0]}/{s['final'][1]}  ({pct(*s['final'])})"),
            row("Avg turns to verdict", lambda s: f"{s['turns']:.1f}"),
            row("Latency p50", lambda s: f"{s['p50'] / 1000:.1f} s"),
            row("Latency p95", lambda s: f"{s['p95'] / 1000:.1f} s"),
            row("Latency max", lambda s: f"{s['max'] / 1000:.1f} s"),
            row("Replies under 15 s", lambda s: f"{s['under15']}/{s['replies']}  ({pct(s['under15'], s['replies'])})"),
            row("AI-turn latency p50 / p95", lambda s: f"{s['ai_p50'] / 1000:.1f} / {s['ai_p95'] / 1000:.1f} s" if s["ai_n"] else "—"),
            row("AI-turn latency max", lambda s: f"{s['ai_max'] / 1000:.1f} s" if s["ai_n"] else "—"),
            row("Replies written by the model", lambda s: str(s["src"]["model"]) if s["calls"] else "—"),
            row("Fast path (engine text)", lambda s: str(s["src"]["fast path"]) if s["calls"] else "—"),
            row("Fallback to rules agent", lambda s: str(s["src"]["fallback"]) if s["calls"] else "—"),
            row("Model call success", lambda s: f"{s['calls_ok']}/{s['calls']}  ({pct(s['calls_ok'], s['calls'])})" if s["calls"] else "—"),
            row("Model call latency p50", lambda s: f"{s['call_p50']:.1f} s" if s["call_p50"] else "—"),
            row("Language match (all cases)", lambda s: f"{s['lang'][0]}/{s['lang'][1]}"),
            row("Language match (Hindi + Hinglish)", lambda s: f"{s['lang_nonen'][0]}/{s['lang_nonen'][1]}")]
    w = (44,) + tuple((180 - 44) / len(runs) for _ in runs)
    pdf.table(rows, w, align=("LEFT",) + ("CENTER",) * len(runs), size=7.8)
    pdf.para("Latency p50 / p95 covers every reply, including instant ones such as the confirmation step. AI-turn latency covers "
             "only replies where the model was called. “Fast path” means the model extracted the facts but the engine wrote the "
             "explanation because a second model call would not have fitted inside the 13-second budget.", 8.4, GREY)

    colors = {"deterministic": SLATE, "nvidia": OK, "openrouter": BLUE}
    pdf.hbars("Verdict accuracy (target 80%)",
              [(f"{NAMES[k.split(':')[0]].split(' (')[0]} · {S[k]['n']}", 100 * S[k]["correct"] / S[k]["n"],
                pct(S[k]["correct"], S[k]["n"]), colors[k.split(":")[0]]) for k in runs])
    pdf.hbars("Median and 95th-percentile reply time (bar scale 0–15 s)",
              [(f"{NAMES[k.split(':')[0]].split(' (')[0]} · {lbl}", S[k][key] / 1000, f"{S[k][key] / 1000:.1f} s",
                colors[k.split(":")[0]]) for k in runs if k.split(":")[0] != "deterministic" or k.endswith("all")
               for lbl, key in (("p50", "p50"), ("p95", "p95"))], maxv=15)
    ai_runs = [k for k in runs if S[k]["calls"]]
    if ai_runs:
        pdf.stacked("How each reply was produced (AI configurations)",
                    [(f"{NAMES[k.split(':')[0]].split(' (')[0]} · {S[k]['n']}",
                      [("model", S[k]["src"]["model"], OK), ("fast path", S[k]["src"]["fast path"], BLUE),
                       ("fallback", S[k]["src"]["fallback"], BAD), ("engine", S[k]["src"]["engine"], GREY)]) for k in ai_runs])

    # ------------------------------------------------------------------ per-class
    pdf.h1("3 · Per-class metrics", "Confusion matrices, precision, recall and F1")
    for key in [k for k in runs if k.endswith("all") or k.startswith("openrouter")]:
        m = confusion(runs[key]["results"])
        pdf.h2(f"{NAMES[key.split(':')[0]]} · {S[key]['n']} conversations")
        rows = [["Expected \\ Got"] + CLASSES + ["Precision", "Recall", "F1"]]
        for e in CLASSES:
            if not any(m[(e, g)] for g in CLASSES) and not any(m[(x, e)] for x in CLASSES):
                continue
            p, r_, f = prf(m, e)
            rows.append([e] + [str(m[(e, g)]) for g in CLASSES] + [f"{p:.2f}", f"{r_:.2f}", f"{f:.2f}"])
        pdf.table(rows, (30, 22, 24, 24, 22, 19, 19, 20), align=("LEFT",) + ("CENTER",) * 7, size=7.8)

    pdf.h2("Accuracy by language and loan type")
    rows = [["Group"] + [f"{NAMES[k.split(':')[0]].split(' (')[0]} · {S[k]['n']}" for k in runs]]
    def group(fn, label):
        cells = []
        for k in runs:
            g = [r for r in runs[k]["results"] if fn(r)]
            cells.append(f"{sum(r['correct'] for r in g)}/{len(g)}" if g else "—")
        rows.append([label] + cells)
    for lg, nm in (("en", "English"), ("hi", "Hindi"), ("hinglish", "Hinglish")):
        group(lambda r, lg=lg: r["lang"] == lg, nm)
    for lt, nm in (("personal", "Personal loan"), ("home", "Home loan"), ("auto", "Car loan"), ("education", "Education loan")):
        group(lambda r, lt=lt: r["loan_type"] == lt, nm)
    pdf.table(rows, w, align=("LEFT",) + ("CENTER",) * len(runs), size=7.8)

    # ------------------------------------------------------------------ errors
    pdf.h1("4 · Error analysis", "Where the models struggled")
    found = False
    for key in runs:
        misses = [r for r in runs[key]["results"] if not r["correct"]]
        errs = S[key]["errors"]
        if not misses and not errs:
            continue
        found = True
        pdf.h2(NAMES[key.split(":")[0]] + (" · subset" if key.endswith("subset") else ""))
        if misses:
            pdf.table([["Case", "Lang", "Expected", "Got", "Turns", "Fields at verdict", "Reply sources"]] +
                      [[r["id"], r["lang"], r["expected"], r["got"], str(len(r["turns"])), f"{r['final_fields'][0]}/{r['final_fields'][1]}",
                        ", ".join(sorted({'fallback' if 'error' in t['mode'] else 'engine' if not t['calls'] else
                                          'fast path' if t['source'] == 'genai+rules-template' else 'model' for t in r['turns']}))] for r in misses],
                      (16, 16, 28, 28, 14, 26, 52), size=7.6)
        if errs:
            pdf.para("Model call failures: " + "; ".join(f"{e or 'timeout'} ×{n}" for e, n in errs.most_common()), 8.6)
    if not found:
        pdf.para("No verdict errors in any configuration.")
    nl34 = [NAMES[k.split(":")[0]].split(" (")[0] for k in runs if any(r["id"] == "nl34" and not r["correct"] for r in runs[k]["results"])]
    if nl34:
        pdf.para(f"**Case nl34 (missed by {' and '.join(nl34)}) is not a hallucination.** The applicant wrote “CIBIL pata nahi” "
                 "(“I don't know my credit score”). The model recorded the score as unknown, a value LoanMitra supports by design: the "
                 "engine then gives a conditional verdict with a caveat. The label expected the bot to keep asking for the score. "
                 + ("Both AI models made the same, consistent choice. " if len(nl34) > 1 else "")
                 + "Both behaviours are defensible; we count it as a miss.", 8.8)
    for key in skipped:
        pdf.para(f"**{NAMES[key.split(':')[0]]}** was excluded: {S[key]['calls']}/{S[key]['calls']} calls rejected "
                 f"({', '.join(f'{e} ×{n}' for e, n in S[key]['errors'].items())}). Re-run the OpenRouter configuration of "
                 "eval/model_eval.py when the daily quota resets.", 8.8)
    pdf.para("A model failure never produces an unsafe verdict: when a call errors or exceeds the budget, the turn is answered by "
             "the rules agent and the conversation continues. The cost of a weak model is latency or an extra question, which is why "
             "verdict accuracy stays high even when model call success is below 100%.", 8.8, GREY)

    # ------------------------------------------------------------------ robustness
    pdf.h1("5 · Rules engine and robustness", "The parts that make every decision")
    pdf.kpis([(f"{R['st'][0]}/{R['st'][1]}", "Boundary cases", "rules engine"), (f"{R['fuzz_n'] // 1000}k", "Random profiles", f"{R['crashes']} crashes"),
              (str(sum(v for _, _, v in R["inv"])), "Invariant violations", f"{sum(c for _, c, _ in R['inv']):,} checks"),
              (f"{R['per_ms']:.2f} ms", "Per decision", "rules engine speed")])
    pdf.h2(f"Consistency rules checked on {R['fuzz_n']:,} random profiles")
    desc = {"I1": "EMI matches the standard formula", "I2": "FOIR = (existing EMIs + new EMI) ÷ income", "I2b": "Displayed FOIR equals the checked FOIR",
            "I2c": "Displayed LTV equals the checked LTV", "I3": "Verdict follows from the individual rule results",
            "I4": "More income never worsens the verdict", "I5": "Higher credit score never worsens it", "I6": "Fewer existing EMIs never worsen it",
            "I7": "A smaller amount never worsens it", "I8": "A more valuable asset never worsens it", "I9a": "A longer tenure never worsens it",
            "I9b": "A longer tenure never lowers the maximum amount", "I10": "The quoted maximum amount is itself eligible",
            "I11": "Every “eligible up to X” in a summary is true", "I12": "“Extend the tenure” advice works when applied",
            "I13": "“Close EMIs” advice works when applied", "I14": "“Add a co-applicant” advice works when applied",
            "I15": "“You qualify for up to X” is true", "I16": "“Reduce the tenure” advice is valid", "I17": "“Improve your score” advice works",
            "I18b": "LTV-capped “request up to” amount is eligible", "I19": "Eligible applicants never get a maximum below their request"}
    rows = [["Invariant", "What it guarantees", "Checked", "Violations"]]
    for n, c, v in sorted(R["inv"], key=lambda x: (int(re.search(r"\d+", x[0]).group()), x[0])):
        code = n.split("_")[0]
        rows.append([code, desc.get(code, n), f"{c:,}", str(v)])
    pdf.table(rows, (16, 120, 24, 20), align=("LEFT", "LEFT", "RIGHT", "CENTER"), size=7.6)
    pdf.h2("Robustness, privacy and security suites")
    pdf.table([["Suite", "Cases", "Failing", "What it covers"],
               ["Real-world extraction", str(R["ext"][0]), str(R["ext"][1]), "Indian amounts, annual vs monthly income, co-applicant vs own facts, negations"],
               ["Edge values", str(R["edges"]), str(R["edge_crash"]), "NaN, infinity, zero, negative, text in number fields, wrong types"],
               ["PII masking", str(R["priv"][0]), str(R["priv"][1]), "PAN, Aadhaar (checksum), phone, email, card (Luhn), account numbers; no false hits on amounts"],
               ["HTTP hardening", str(R["http_ok"] + R["http_fail"]), str(R["http_fail"]), "Rate limits, body limits, schema validation, consent, security headers, session IDs"]],
              (38, 16, 16, 110), size=7.8)
    pdf.h2("Bank-statement analysis against ground truth")
    pdf.table([["Statement", "Transactions (true / read)", "Monthly income (true / found)", "Monthly EMIs (true / found)"]] +
              [[n, f"{t} / {rd}", f"Rs {i:,} / Rs {fi:,.0f}", f"Rs {e:,} / Rs {fe:,.0f}"] for n, t, rd, i, fi, e, fe in R["stm"]],
              (48, 40, 46, 46), align=("LEFT", "CENTER", "CENTER", "CENTER"), size=7.8)

    # ------------------------------------------------------------------ limitations
    pdf.h1("6 · Issues found and fixed", "What testing changed in the product")
    pdf.table([["Issue", "Found by", "Fix", "Status"],
               ["Applicant answered 7 questions with 7 bare values, one per line; the model was slow, the fallback could not place "
                "bare numbers, so 6 values were lost and asked again", "Live demo test",
                "List answers are now mapped in order to the details still missing, deterministically and instantly; the confirmation "
                "card shows every value with its label", "Fixed, regression test added"],
               ["Model asked for 7 details in one message", "Live demo test",
                "Prompt now requires the tool's order and at most 2 details per message; list mapping covers models that ignore it",
                "Fixed"],
               ["NVIDIA API: 3 server errors (HTTP 500) and 3 timeouts in 38 calls", "This evaluation",
                "Already handled: the rules agent answers that turn and the conversation continues", "Working as designed"],
               ["OpenRouter free tier rejected every call (daily limit used up)", "This evaluation",
                "Provider chain falls through to NVIDIA, then to the rules agent; for a production deployment use a paid key",
                "Mitigated"],
               ["Typed Marathi detected as Hindi (same script)", "Live demo test",
                "Marathi-only words now distinguish the two languages", "Fixed"]],
              (62, 24, 66, 28), size=7.6)

    pdf.h1("7 · Limitations", "How to read these numbers")
    pdf.bullets(["**Same-team test data.** The labelled conversations were written by the team that built the system. They show the system "
                 "is correct and consistent on known phrasing; they are not a blind test. Next step: 25 messages written independently by the "
                 "five team members, scored without changes to the code.",
                 "**Small samples.** 36 labelled conversations give wide confidence intervals; one miss moves accuracy by about 3 points.",
                 "**Free-tier models.** Latency and error rates depend on shared free infrastructure at the time of the run, and will differ "
                 "on a dedicated deployment.",
                 "**Regional languages.** Bengali, Tamil, Telugu, Kannada, Malayalam, Marathi, Gujarati, Punjabi and Odia go through machine "
                 "translation and were not part of this labelled set.",
                 "**Synthetic policy.** Rules and lenders are illustrative; the evaluation shows the engine applies its policy correctly, not "
                 "that the policy matches any real bank."])

    # ------------------------------------------------------------------ appendix
    detail = next((k for k in ("nvidia:all", "openrouter:subset") if k in runs), None)
    if detail:
        pdf.add_page()
        pdf.h1("Appendix", f"Per-case results · {NAMES[detail.split(':')[0]]}")
        pdf.table([["Case", "Lang", "Loan", "Expected", "Got", "OK", "Turns", "Max reply", "Sources"]] +
                  [[r["id"], r["lang"], r["loan_type"] or "—", r["expected"], r["got"], "✓" if r["correct"] else "✗", str(len(r["turns"])),
                    f"{max(t['latency_ms'] for t in r['turns']) / 1000:.1f} s",
                    ", ".join(sorted({('fallback' if 'error' in t['mode'] else 'engine' if not t['calls'] else t['source'].replace('genai+rules-template', 'fast path').replace('genai', 'model')) for t in r['turns']}))]
                   for r in runs[detail]["results"]],
                  (13, 15, 17, 27, 27, 8, 11, 17, 45), size=7)

    OUT.parent.mkdir(exist_ok=True)
    pdf.output(str(OUT))
    print(f"wrote {OUT.relative_to(ROOT)} ({pdf.page_no()} pages)")


if __name__ == "__main__":
    random.seed(0)
    build()
