/* LoanMitra chat UI — vanilla JS, no build step. */
(() => {
  const $ = (id) => document.getElementById(id);
  const messagesEl = $("messages"), input = $("input"), sendBtn = $("sendBtn"), form = $("composer");
  const langSelect = $("langSelect"), micBtn = $("micBtn"), ttsBtn = $("ttsBtn"), resetBtn = $("resetBtn");

  let sessionId = null;
  let tts = false;
  let busy = false;

  const FIELD_LABELS = {
    loan_type: "Loan type", loan_amount: "Amount", tenure_years: "Tenure", age: "Age", monthly_income: "Net income / month",
    employment_type: "Employment", employment_months: "Experience", credit_score: "Credit score", existing_emi: "Existing EMIs",
    property_value: "Property value", vehicle_price: "Vehicle price", study_abroad: "Study location",
    co_applicant_income: "Co-applicant income", co_applicant_credit_score: "Co-applicant score", co_applicant_existing_emi: "Co-applicant EMIs",
  };
  const RULE_LABELS = {
    tenure_range: "Tenure within product limits", age: "Age at loan maturity", employment_vintage: "Work experience",
    min_income: "Minimum income", credit_score: "Credit score cut-off", credit_score_margin: "Score margin",
    amount_range: "Amount within product range", ltv: "Loan-to-value", collateral: "Collateral", foir: "Repayment capacity (FOIR)",
    foir_margin: "FOIR margin", income_multiple: "Income multiple cap",
  };

  const fmtINR = (n) => {
    if (n == null || isNaN(n)) return "–";
    n = Number(n);
    if (n >= 1e7) return "₹" + (n / 1e7).toFixed(2).replace(/\.?0+$/, "") + " Cr";
    if (n >= 1e5) return "₹" + (n / 1e5).toFixed(2).replace(/\.?0+$/, "") + " L";
    return "₹" + Math.round(n).toLocaleString("en-IN");
  };
  const showValue = (k, v) => {
    if (k === "loan_type") return { personal: "Personal loan", home: "Home loan", auto: "Car loan", education: "Education loan" }[v] || v;
    if (k === "employment_type") return v === "self_employed" ? "Self-employed" : "Salaried";
    if (k === "study_abroad") return v ? "Abroad" : "India";
    if (k === "tenure_years") return `${v} yrs`;
    if (k === "employment_months") return `${v} months`;
    if (k === "age" || k.includes("score")) return String(v);
    return fmtINR(v);
  };
  const esc = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  /** Minimal markdown: bold, bullets. Everything else stays plain text. */
  function renderText(text) {
    const lines = esc(text).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").split("\n");
    let html = "", inList = false;
    for (const ln of lines) {
      const m = ln.match(/^\s*(?:[-•*]|\d+[.)])\s+(.*)$/);
      if (m) { if (!inList) { html += "<ul>"; inList = true; } html += `<li>${m[1]}</li>`; }
      else { if (inList) { html += "</ul>"; inList = false; } html += ln + "\n"; }
    }
    if (inList) html += "</ul>";
    return html.replace(/\n+$/, "");
  }

  function addMessage(role, text, tag) {
    const wrap = document.createElement("div");
    wrap.className = `msg ${role}`;
    wrap.innerHTML = `<div class="bubble">${renderText(text)}${tag ? `<div class="tag">${esc(tag)}</div>` : ""}</div>`;
    messagesEl.appendChild(wrap);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return wrap;
  }
  function addTyping() {
    const el = document.createElement("div");
    el.className = "msg bot"; el.innerHTML = `<div class="bubble typing"><span></span><span></span><span></span></div>`;
    messagesEl.appendChild(el); messagesEl.scrollTop = messagesEl.scrollHeight;
    return el;
  }

  // ------------------------------------------------------------ dashboard
  function updateDashboard(r) {
    const ev = r.evaluation;
    const profile = r.profile || {};
    const missing = r.missing_fields || [];

    // profile
    const pl = $("profileList"); pl.innerHTML = "";
    const keys = Object.keys(profile);
    for (const k of keys) pl.insertAdjacentHTML("beforeend", `<li><span>${FIELD_LABELS[k] || k}</span><b>${esc(showValue(k, profile[k]))}</b></li>`);
    for (const k of missing) if (!(k in profile)) pl.insertAdjacentHTML("beforeend", `<li class="missing"><span>${FIELD_LABELS[k] || k}</span></li>`);
    const total = keys.length + missing.filter((k) => !(k in profile)).length;
    $("profileProgress").textContent = total ? `${keys.length}/${total}` : "";

    // status + gauge
    const pill = $("statusPill"), gaugeFill = $("gaugeFill");
    if (ev) {
      pill.className = `pill pill-${ev.status}`;
      pill.textContent = { ELIGIBLE: "Eligible", CONDITIONAL: "Conditionally eligible", NOT_ELIGIBLE: "Not eligible" }[ev.status] || ev.status;
      $("statusSummary").textContent = ev.summary;
      $("gaugeScore").textContent = ev.score;
      gaugeFill.style.strokeDashoffset = String(157 - (157 * ev.score) / 100);
      gaugeFill.style.stroke = ev.status === "ELIGIBLE" ? "var(--ok)" : ev.status === "CONDITIONAL" ? "var(--warn)" : "var(--bad)";
      $("kpiEmi").textContent = ev.emi ? fmtINR(ev.emi) + "/mo" : "–";
      $("kpiFoir").textContent = ev.foir != null ? Math.round(ev.foir * 100) + "%" : "–";
      $("kpiMax").textContent = fmtINR(ev.max_eligible_amount);
      $("kpiRate").textContent = ev.interest_rate ? ev.interest_rate + "% p.a." : "–";

      const cl = $("checksList"); cl.innerHTML = "";
      for (const c of ev.checks) {
        const cls = c.passed ? "pass" : c.hard ? "fail" : "warn";
        const icon = c.passed ? "✓" : c.hard ? "✕" : "!";
        cl.insertAdjacentHTML("beforeend", `<li><span class="dot ${cls}">${icon}</span><div><b>${RULE_LABELS[c.rule] || c.rule}</b><br><span class="muted">${esc(c.detail)}</span></div></li>`);
      }
      $("checksEmpty").hidden = ev.checks.length > 0;

      $("stepsCard").hidden = !ev.improvements.length;
      $("stepsList").innerHTML = ev.improvements.map((s) => `<li>${esc(s)}</li>`).join("");
      $("docsCard").hidden = !(r.documents && r.documents.length);
      $("docsList").innerHTML = (r.documents || []).map((d) => `<li>${esc(d)}</li>`).join("");
    } else {
      pill.className = "pill pill-INCOMPLETE";
      pill.textContent = keys.length ? `Collecting details (${keys.length}/${total})` : "Awaiting details";
      $("statusSummary").textContent = missing.length ? "Still needed: " + missing.map((k) => (FIELD_LABELS[k] || k).toLowerCase()).join(", ") : "";
    }

    // meta
    const lb = $("latencyBadge");
    lb.textContent = `⏱ ${r.latency_ms} ms`;
    lb.className = "badge " + (r.latency_ms < 15000 ? "badge-ok" : "badge-bad");
    const pb = $("piiBadge");
    if (r.pii_masked && r.pii_masked.length) { pb.textContent = `🔒 masked: ${r.pii_masked.join(", ")}`; pb.className = "badge badge-warn"; }
    else { pb.textContent = "🔒 PII guard on"; pb.className = "badge badge-muted"; }
    $("langBadge").textContent = "🌐 " + ({ en: "English", hi: "हिंदी", hinglish: "Hinglish" }[r.language] || r.language);
    const mb = $("modeBadge");
    mb.textContent = r.mode.startsWith("genai") ? `GenAI · ${r.model || "Claude"}` : "Deterministic mode (no API key)";
    mb.className = "badge " + (r.mode === "genai" ? "badge-ok" : "badge-warn");
  }

  function resetDashboard() {
    $("profileList").innerHTML = ""; $("profileProgress").textContent = "";
    $("statusPill").className = "pill pill-idle"; $("statusPill").textContent = "Awaiting details";
    $("statusSummary").textContent = "Share your details in the chat and the verdict appears here, with every rule that was checked.";
    $("gaugeScore").textContent = "–"; $("gaugeFill").style.strokeDashoffset = "157";
    ["kpiEmi", "kpiFoir", "kpiMax", "kpiRate"].forEach((id) => ($(id).textContent = "–"));
    $("checksList").innerHTML = ""; $("checksEmpty").hidden = false;
    $("stepsCard").hidden = true; $("docsCard").hidden = true;
  }

  // ------------------------------------------------------------ send
  async function send(text) {
    text = (text || input.value).trim();
    if (!text || busy) return;
    busy = true; sendBtn.disabled = true;
    input.value = ""; autosize();
    addMessage("user", text);
    const typing = addTyping();
    try {
      const res = await fetch("/api/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, message: text, language: langSelect.value }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const r = await res.json();
      sessionId = r.session_id;
      typing.remove();
      addMessage("bot", r.reply, `${r.mode} · ${r.latency_ms} ms`);
      updateDashboard(r);
      if (tts) speak(r.reply, r.language);
    } catch (e) {
      typing.remove();
      addMessage("bot", "Sorry, something went wrong on my side. Please try again. (" + e.message + ")");
    } finally {
      busy = false; sendBtn.disabled = false; input.focus();
    }
  }

  form.addEventListener("submit", (e) => { e.preventDefault(); send(); });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
  function autosize() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 140) + "px"; }
  input.addEventListener("input", autosize);

  resetBtn.addEventListener("click", async () => {
    if (sessionId) await fetch("/api/reset", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId }) });
    sessionId = null;
    messagesEl.querySelectorAll(".msg").forEach((m, i) => { if (i > 0) m.remove(); });
    resetDashboard();
    addMessage("bot", "Fresh start. Which loan are you looking for, and tell me a bit about yourself?");
  });

  // ------------------------------------------------------------ voice
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  let rec = null;
  if (!SR) { micBtn.title = "Voice input needs Chrome/Edge"; micBtn.disabled = true; micBtn.style.opacity = .5; }
  micBtn.addEventListener("click", () => {
    if (rec) { rec.stop(); return; }
    rec = new SR();
    rec.lang = langSelect.value === "hi" || langSelect.value === "hinglish" ? "hi-IN" : "en-IN";
    rec.interimResults = true;
    micBtn.classList.add("listening");
    let finalText = "";
    rec.onresult = (ev) => {
      let interim = "";
      for (const r of ev.results) (r.isFinal ? (finalText += r[0].transcript + " ") : (interim += r[0].transcript));
      input.value = (finalText + interim).trim(); autosize();
    };
    rec.onend = () => { micBtn.classList.remove("listening"); rec = null; if (input.value.trim()) send(); };
    rec.onerror = () => { micBtn.classList.remove("listening"); rec = null; };
    rec.start();
  });

  ttsBtn.addEventListener("click", () => {
    tts = !tts; ttsBtn.setAttribute("aria-pressed", String(tts)); ttsBtn.textContent = tts ? "🔊" : "🔈";
    if (!tts) window.speechSynthesis?.cancel();
  });
  function speak(text, lang) {
    if (!window.speechSynthesis) return;
    window.speechSynthesis.cancel();
    const clean = text.replace(/[•✅🟡🔴→☐*#_]/g, " ").replace(/\s+/g, " ").slice(0, 900);
    const u = new SpeechSynthesisUtterance(clean);
    u.lang = /[ऀ-ॿ]/.test(text) || lang === "hi" ? "hi-IN" : "en-IN";
    u.rate = 1.02;
    window.speechSynthesis.speak(u);
  }

  // ------------------------------------------------------------ boot
  (async () => {
    try {
      const h = await (await fetch("/api/health")).json();
      const mb = $("modeBadge");
      mb.textContent = h.mode === "genai" ? `GenAI · ${h.model}` : "Deterministic mode (no API key)";
      mb.className = "badge " + (h.mode === "genai" ? "badge-ok" : "badge-warn");
      const samples = await (await fetch("/api/samples")).json();
      $("samples").innerHTML = samples.map((s) => `<button type="button" class="chip" data-text="${esc(s.text)}">${esc(s.label)}</button>`).join("");
      $("samples").querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => send(c.dataset.text)));
    } catch (e) { console.error(e); }
    input.focus();
  })();
})();
