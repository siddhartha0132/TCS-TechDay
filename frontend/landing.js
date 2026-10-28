/* LoanMitra landing: live rules-engine explanation, EMI planner, scroll progress, lazy 3D stage. */
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtINR = (n) => {
  n = Number(n);
  if (!isFinite(n)) return "—";
  if (n >= 1e7) return "₹" + (Math.floor(n / 1e5) / 100) + " Cr";
  if (n >= 1e5) return "₹" + (Math.floor(n / 1e3) / 100) + " L";
  return "₹" + Math.round(n).toLocaleString("en-IN");
};

// ------------------------------------------------------------ nav
const nav = document.querySelector(".nav");
const onScroll = () => nav.classList.toggle("solid", window.scrollY > 40);
window.addEventListener("scroll", onScroll, { passive: true });
onScroll();

// ------------------------------------------------------------ jury brief: criterion tabs -> "how we did it" panels
const scoreTabs = [...document.querySelectorAll(".scorecard .score")];
scoreTabs.forEach((tab) => tab.addEventListener("click", () => {
  scoreTabs.forEach((t) => {
    const on = t === tab;
    t.setAttribute("aria-selected", String(on));
    document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
  });
}));

// ------------------------------------------------------------ scroll progress shared with the 3D stage
// 0 = hero; 1..5 = story chapters; >5 = past the story (content sections cover the stage).
export function storyProgress() {
  const chapters = [...document.querySelectorAll("[data-chapter]")];
  const mid = window.innerHeight / 2;
  for (let i = 0; i < chapters.length; i++) {
    const r = chapters[i].getBoundingClientRect();
    if (r.top <= mid && r.bottom > mid) return i + (mid - r.top) / r.height - 0.5;
  }
  const last = chapters[chapters.length - 1].getBoundingClientRect();
  return last.bottom <= mid ? chapters.length : 0;
}
window.__storyProgress = storyProgress;

// ------------------------------------------------------------ chapter 4: a live evaluation from the real rules engine
const SAMPLE = { loan_type: "home", loan_amount: 6000000, tenure_years: 20, age: 38, employment_type: "self_employed",
  monthly_income: 110000, credit_score: 720, existing_emi: 25000, property_value: 7000000 };
const LABELS = { tenure_range: "Tenure", age: "Age at maturity", employment: "Employment", min_income: "Minimum income",
  credit_score: "Credit score", credit_score_margin: "Score margin", amount_range: "Amount range", ltv: "Loan-to-value",
  collateral: "Collateral", foir: "Repayment ratio (FOIR)", foir_margin: "FOIR margin", income_multiple: "Income multiple" };
(async () => {
  try {
    const res = await fetch("/api/evaluate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ applicant: SAMPLE }) });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const ev = await res.json();
    const name = { ELIGIBLE: "ELIGIBLE", CONDITIONAL: "CONDITIONALLY ELIGIBLE", NOT_ELIGIBLE: "NOT ELIGIBLE" }[ev.status] || ev.status;
    $("explain").innerHTML =
      `<span class="verdict ${esc(ev.status)}">VERDICT · ${esc(name)}</span>` +
      `<p class="summary">${esc(ev.summary)}</p>` +
      `<ul class="checks">${ev.checks.map((c) => {
        const cls = c.passed ? "pass" : c.hard ? "fail" : "warn";
        return `<li><span class="s ${cls}">${c.passed ? "✓" : c.hard ? "✕" : "!"}</span><span><b>${esc(LABELS[c.rule] || c.rule)}</b> — ${esc(c.detail)}</span></li>`;
      }).join("")}</ul>` +
      `<p class="meta">NEXT STEPS</p><ol class="steps">${ev.improvements.slice(0, 3).map((s) => `<li>${esc(s)}</li>`).join("")}</ol>` +
      `<p class="meta sample-note">Sample applicant: home loan ₹60 L · income ₹1.1 L/mo · EMI ₹25k · CIBIL 720 · flat ₹70 L</p>`;
  } catch (e) {
    $("explain").innerHTML = `<p class="muted">The live evaluation couldn't load (${esc(e.message)}). Try the chat instead.</p>`;
  }
})();

// ------------------------------------------------------------ chapter 5: EMI planner
function emi(p, rate, years) {
  const n = Math.max(1, Math.round(years * 12)), r = rate / 1200;
  return r === 0 ? p / n : (p * r * (1 + r) ** n) / ((1 + r) ** n - 1);
}
function updateCalc() {
  const p = +$("cAmount").value, rate = +$("cRate").value, years = +$("cTenure").value;
  const m = emi(p, rate, years), total = m * years * 12, interest = total - p;
  $("cAmountV").textContent = fmtINR(p);
  $("cRateV").textContent = `${rate.toFixed(2)}% p.a.`;
  $("cTenureV").textContent = `${years} ${years === 1 ? "year" : "years"}`;
  $("cEmi").textContent = fmtINR(m);
  $("cInt").textContent = fmtINR(interest);
  $("cTot").textContent = fmtINR(total);
  const share = Math.round((p / total) * 100);
  $("cBarP").style.width = `${share}%`;
  $("cBarI").style.width = `${100 - share}%`;
  const q = `I need a loan of ${p} rupees for ${years} years. What is my eligibility?`;
  $("cGo").href = `/chat?q=${encodeURIComponent(q)}`;
  window.__emiPlan = { amount: p, rate, years, emi: m };
}
["cAmount", "cRate", "cTenure"].forEach((id) => $(id).addEventListener("input", updateCalc));
updateCalc();

// ------------------------------------------------------------ 3D stage (lazy, after first paint)
function webglOK() {
  try {
    const c = document.createElement("canvas");
    return !!(window.WebGL2RenderingContext && c.getContext("webgl2"));
  } catch { return false; }
}
const start = () => {
  if (!webglOK()) { document.body.classList.add("no-webgl"); return; }
  import("/static/scene3d.js").then((m) => m.initScene($("stage"), $("labels"), storyProgress))
    .catch((e) => { console.warn("3D stage unavailable", e); document.body.classList.add("no-webgl"); });
};
if ("requestIdleCallback" in window) requestIdleCallback(start, { timeout: 1200 }); else setTimeout(start, 300);

// Deep link to a story chapter, e.g. /?ch=5 opens the EMI planner (handy in demos).
const ch = new URLSearchParams(location.search).get("ch");
if (ch && /^[0-5]$/.test(ch)) {
  const el = document.querySelector(`[data-chapter="${ch}"]`);
  if (el) requestAnimationFrame(() => {
    const r = el.getBoundingClientRect();
    window.scrollTo({ top: r.top + scrollY + r.height / 2 - innerHeight / 2, behavior: "instant" });
  });
}
