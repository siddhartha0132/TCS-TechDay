/* LoanMitra UI — vanilla JS, no build step, CSP-safe (no inline handlers or styles in markup). */
(() => {
  const $ = (id) => document.getElementById(id);
  const messagesEl = $("messages"), input = $("input"), sendBtn = $("sendBtn"), form = $("composer");
  const langSelect = $("langSelect"), micBtn = $("micBtn"), ttsBtn = $("ttsBtn"), resetBtn = $("resetBtn");

  let sessionId = null, tts = false, busy = false, voiceEngine = "browser";
  let lastProfile = {}, lastEval = null;

  const PRODUCT = {
    personal: { label: "Personal Loan", amounts: [200000, 500000, 1000000], tenures: [2, 3, 5], tenure: [1, 5] },
    home: { label: "Home Loan", amounts: [2500000, 5000000, 7500000], tenures: [10, 20, 30], tenure: [5, 30] },
    auto: { label: "Car Loan", amounts: [500000, 800000, 1200000], tenures: [3, 5, 7], tenure: [1, 7] },
    education: { label: "Education Loan", amounts: [1000000, 2000000, 4000000], tenures: [5, 10, 15], tenure: [5, 15] },
  };
  const FIELD_LABELS = {
    loan_type: "Loan type", loan_amount: "Amount", tenure_years: "Tenure", age: "Age", monthly_income: "Net income / month",
    employment_type: "Employment", employment_months: "Experience", credit_score: "Credit score", existing_emi: "Existing EMIs",
    property_value: "Property value", vehicle_price: "Vehicle price", study_abroad: "Study location",
    co_applicant_income: "Co-applicant income", co_applicant_credit_score: "Co-applicant score", co_applicant_existing_emi: "Co-applicant EMIs",
  };
  const RULE_LABELS = {
    tenure_range: "Tenure within product limits", age: "Age at loan maturity", employment: "Employment", employment_vintage: "Work experience",
    min_income: "Minimum income", credit_score: "Credit score", credit_score_margin: "Score margin", amount_range: "Amount within product range",
    ltv: "Loan-to-value", collateral: "Collateral", foir: "Repayment capacity (FOIR)", foir_margin: "FOIR margin", income_multiple: "Income multiple cap",
  };
  const VERDICT = { ELIGIBLE: "Eligible", CONDITIONAL: "Conditionally eligible", NOT_ELIGIBLE: "Not eligible right now" };
  const STEP_FIELDS = [
    ["loan_type", "loan_amount", "tenure_years"],
    ["age", "employment_type", "study_abroad"],
    ["monthly_income", "credit_score", "existing_emi", "property_value", "vehicle_price", "co_applicant_income", "co_applicant_credit_score", "co_applicant_existing_emi"],
  ];

  const fmtINR = (n) => {
    if (n == null || isNaN(n)) return "–";
    n = Number(n);
    if (n >= 1e7) return "₹" + (Math.floor(n / 1e5) / 100).toString() + " Cr";
    if (n >= 1e5) return "₹" + (Math.floor(n / 1e3) / 100).toString() + " L";
    return "₹" + Math.round(n).toLocaleString("en-IN");
  };
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const showValue = (k, v) => {
    if (v === "unknown") return "Not known";
    if (k === "loan_type") return PRODUCT[v]?.label || v;
    if (k === "employment_type") return { salaried: "Salaried", self_employed: "Self-employed", not_employed: "Not employed" }[v] || v;
    if (k === "study_abroad") return v ? "Abroad" : "India";
    if (k === "tenure_years") return `${+v.toFixed ? +Number(v).toFixed(1) : v} yrs`;
    if (k === "employment_months") return `${v} months`;
    if (k === "age" || k.includes("score")) return String(v);
    return fmtINR(v);
  };

  /** Minimal markdown: bold + bullets; everything else stays escaped plain text. */
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

  function addMessage(role, text, tag, verdict) {
    const wrap = document.createElement("div");
    wrap.className = `msg ${role}`;
    // The chip comes from the rules engine, not the model: it is the authoritative decision.
    const chip = verdict && VERDICT[verdict.status]
      ? `<div class="verified v-${verdict.status}" title="${esc(verdict.summary)}">🔒 Rules-engine verdict: ${VERDICT[verdict.status]}</div>` : "";
    const avatar = role === "bot" ? `<div class="avatar" aria-hidden="true">₹</div>` : "";
    wrap.innerHTML = `${avatar}<div class="bubble">${chip}${renderText(text)}${tag ? `<div class="tag">${esc(tag)}</div>` : ""}</div>`;
    messagesEl.appendChild(wrap);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }
  function addTyping() {
    const el = document.createElement("div");
    el.className = "msg bot";
    el.innerHTML = `<div class="avatar" aria-hidden="true">₹</div><div class="bubble typing"><span></span><span></span><span></span></div>`;
    messagesEl.appendChild(el); messagesEl.scrollTop = messagesEl.scrollHeight;
    return el;
  }

  // ------------------------------------------------------------ quick replies
  function quickReplies(field, profile, ev) {
    const p = PRODUCT[profile.loan_type] || PRODUCT.personal;
    const co = profile.loan_type === "education" ? "My father's " : "";
    switch (field) {
      case "__confirm__": return [["✅ Yes, confirm", "Yes, confirm"], ["✏️ Change something", "__edit__"]];
      case "loan_type": return Object.entries(PRODUCT).map(([k, v]) => [v.label, `I want a ${v.label.toLowerCase()}`]);
      case "loan_amount": return p.amounts.map((a) => [fmtINR(a), `${a / 1e5} lakh`]);
      case "tenure_years": return p.tenures.map((t) => [`${t} years`, `${t} years`]);
      case "monthly_income": return [30000, 50000, 75000, 100000].map((a) => [fmtINR(a), `My salary is ${a} per month`]);
      case "co_applicant_income": return [50000, 100000, 150000].map((a) => [fmtINR(a), `${co}income is ${a} per month`]);
      case "employment_type": return [["Salaried", "I am salaried"], ["Self-employed", "I am self-employed"], ["Not working", "I am not working"]];
      case "credit_score": case "co_applicant_credit_score":
        return [["750+", `${co}credit score is 770`], ["700–749", `${co}credit score is 725`], ["650–699", `${co}credit score is 675`], ["Don't know", "I don't know"]];
      case "existing_emi": case "co_applicant_existing_emi":
        return [["No EMIs", "No EMIs"], ["₹5,000", "5000"], ["₹10,000", "10000"], ["₹20,000", "20000"]];
      case "study_abroad": return [["In India", "The course is in India"], ["Abroad", "The course is abroad"]];
      case "property_value": return [5000000, 7500000, 10000000].map((a) => [fmtINR(a), `Property is worth ${a / 1e5} lakh`]);
      case "vehicle_price": return [700000, 1000000, 1500000].map((a) => [fmtINR(a), `On-road price is ${a / 1e5} lakh`]);
      default: break;
    }
    if (ev) {
      const t = Number(profile.tenure_years || 0), max = p.tenure[1];
      const out = [["🏦 Compare banks", "Which bank is best for me?"], ["📄 Documents needed", "Which documents do I need?"]];
      if (t && t < max) out.unshift([`What if ${Math.min(max, t + (max > 10 ? 5 : 2))} years?`, `What if I take it for ${Math.min(max, t + (max > 10 ? 5 : 2))} years?`]);
      out.push(["↺ New check", "__reset__"]);
      return out;
    }
    return [];
  }
  function renderQuick(field, profile, ev) {
    const items = quickReplies(field, profile, ev);
    $("quick").innerHTML = items.map(([label, text], i) =>
      `<button type="button" class="chip${text === "__reset__" ? " alt" : ""}" data-i="${i}">${esc(label)}</button>`).join("");
    $("quick").querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => {
      const text = items[+c.dataset.i][1];
      if (text === "__reset__") resetAll();
      else if (text === "__edit__") { input.placeholder = "e.g. “my salary is 65,000 per month”"; input.focus(); }
      else send(text);
    }));
  }

  // ------------------------------------------------------------ stepper + products
  function updateStepper(profile, ev) {
    const required = new Set([...(lastMissing || []), ...Object.keys(profile)]);
    let active = 3;
    for (let i = 0; i < STEP_FIELDS.length; i++) {
      const need = STEP_FIELDS[i].filter((f) => required.has(f));
      if (!profile.loan_type && i === 0) { active = 0; break; }
      if (need.some((f) => !(f in profile))) { active = i; break; }
    }
    if (!ev && active === 3) active = 2;
    document.querySelectorAll("#stepper li").forEach((li) => {
      const s = +li.dataset.step;
      li.className = s < active || (ev && s === 3) ? "done" : s === active ? "active" : "";
    });
  }
  let lastMissing = [];
  function selectProduct(type) {
    document.querySelectorAll(".product").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.type === type)));
  }
  document.querySelectorAll(".product").forEach((b) => b.addEventListener("click", () => {
    selectProduct(b.dataset.type);
    send(`I want a ${PRODUCT[b.dataset.type].label.toLowerCase()}`);
  }));

  // ------------------------------------------------------------ dashboard
  function updateDashboard(r) {
    const ev = r.evaluation, profile = r.profile || {}, missing = r.missing_fields || [];
    lastProfile = profile; lastEval = ev; lastMissing = missing;
    if (profile.loan_type) selectProduct(profile.loan_type);

    const pl = $("profileList"); pl.innerHTML = "";
    const keys = Object.keys(profile);
    for (const k of keys) pl.insertAdjacentHTML("beforeend", `<li><span>${FIELD_LABELS[k] || esc(k)}</span><b>${esc(showValue(k, profile[k]))}</b></li>`);
    for (const k of missing) if (!(k in profile)) pl.insertAdjacentHTML("beforeend", `<li class="missing"><span>${FIELD_LABELS[k] || esc(k)}</span></li>`);
    const total = keys.length + missing.filter((k) => !(k in profile)).length;
    $("profileProgress").textContent = total ? `${keys.length}/${total}` : "";

    const pill = $("statusPill"), gaugeFill = $("gaugeFill");
    if (ev) {
      pill.className = `pill pill-${ev.status}`;
      pill.textContent = VERDICT[ev.status] || ev.status;
      const eligibleAmt = ev.status === "ELIGIBLE" ? ev.requested_amount : ev.max_eligible_amount;
      $("resultLabel").textContent = ev.status === "ELIGIBLE" ? "You're eligible for" : ev.status === "CONDITIONAL" ? "You're eligible for up to" : "Eligible amount today";
      $("resultAmount").textContent = ev.status === "NOT_ELIGIBLE" ? "Not yet" : fmtINR(eligibleAmt);
      $("resultSub").textContent = ev.summary;
      $("gaugeScore").textContent = ev.score;
      gaugeFill.style.strokeDashoffset = String(157 - (157 * ev.score) / 100);
      gaugeFill.style.stroke = ev.status === "ELIGIBLE" ? "var(--ok)" : ev.status === "CONDITIONAL" ? "var(--warn)" : "var(--bad)";
      $("kpiEmi").textContent = ev.emi ? fmtINR(ev.emi) : "–";
      $("kpiRate").textContent = ev.interest_rate ? ev.interest_rate + "%" : "–";
      $("kpiTenure").textContent = ev.tenure_years ? ev.tenure_years + " yrs" : "–";
      $("kpiFoir").textContent = ev.foir != null ? Math.round(ev.foir * 100) + "%" : "–";

      const cl = $("checksList"); cl.innerHTML = "";
      for (const c of ev.checks) {
        const cls = c.passed ? "pass" : c.hard ? "fail" : "warn";
        cl.insertAdjacentHTML("beforeend", `<li><span class="dot ${cls}">${c.passed ? "✓" : c.hard ? "✕" : "!"}</span><div><b>${RULE_LABELS[c.rule] || esc(c.rule)}</b><br><span class="muted">${esc(c.detail)}</span></div></li>`);
      }
      $("checksEmpty").hidden = ev.checks.length > 0;
      $("stepsCard").hidden = !ev.improvements.length;
      $("stepsList").innerHTML = ev.improvements.map((s) => `<li>${esc(s)}</li>`).join("");
      $("docsCard").hidden = !(r.documents && r.documents.length);
      $("docsList").innerHTML = (r.documents || []).map((d) => `<li>${esc(d)}</li>`).join("");
      setupSimulator(profile, ev);
      refreshLenders(profile);
    } else {
      pill.className = "pill pill-INCOMPLETE";
      pill.textContent = r.pending_confirmation ? "Confirm your details" : keys.length ? `Collecting details · ${keys.length}/${total}` : "Awaiting details";
      $("resultLabel").textContent = "Your eligible amount";
      $("resultAmount").textContent = r.pending_confirmation ? "One step left" : "—";
      $("resultSub").textContent = r.pending_confirmation
        ? "Check the values in the chat and confirm — your result appears right after."
        : missing.length ? "Still needed: " + missing.map((k) => (FIELD_LABELS[k] || k).toLowerCase()).join(", ") : "";
      $("simCard").hidden = true;
      $("lendersCard").hidden = true;
    }
    updateStepper(profile, ev);
    renderQuick(r.pending_confirmation ? "__confirm__" : r.next_field, profile, ev);

    const lb = $("latencyBadge");
    lb.textContent = `⏱ ${(r.latency_ms / 1000).toFixed(1)} s`;
    lb.className = "badge " + (r.latency_ms < 15000 ? "badge-ok" : "badge-bad");
    const pb = $("piiBadge");
    if (r.pii_masked && r.pii_masked.length) { pb.textContent = `🔒 masked: ${r.pii_masked.join(", ")}`; pb.className = "badge badge-warn"; }
    else { pb.textContent = "🔒 PII guard on"; pb.className = "badge badge-muted"; }
    const langName = [...langSelect.options].find((o) => o.value === r.language);
    $("langBadge").textContent = "🌐 " + (r.language === "en" ? "English" : langName ? langName.textContent : r.language);
    setModeBadge(r.mode, r.model);
  }
  function setModeBadge(mode, model) {
    if (mode) { currentMode = mode; currentModel = model; }
    const mb = $("modeBadge");
    const short = (model || "").split("/").pop().replace(":free", "");
    mb.textContent = mode === "genai" ? `✨ AI · ${short}` : mode && mode.includes("error") ? "Rules engine (AI busy)" : "Rules engine";
    mb.className = "badge " + (mode === "genai" ? "badge-ok" : "badge-warn");
  }

  // ------------------------------------------------------------ what-if sliders (rules engine, instant)
  let simTimer = null;
  function setupSimulator(profile, ev) {
    const p = PRODUCT[profile.loan_type];
    if (!p || !profile.loan_amount) { $("simCard").hidden = true; return; }
    const top = Math.max(profile.loan_amount, ev.max_eligible_amount || 0) * 1.6;
    const step = top > 5e6 ? 100000 : 10000;
    const a = $("simAmount"), t = $("simTenure");
    a.min = String(step); a.max = String(Math.ceil(top / step) * step); a.step = String(step); a.value = String(profile.loan_amount);
    t.min = String(p.tenure[0]); t.max = String(p.tenure[1]); t.value = String(Math.round(profile.tenure_years || p.tenure[0]));
    $("simCard").hidden = false;
    paintSim(); $("simOut").textContent = "Move the sliders to see your eligibility change instantly.";
  }
  function paintSim() {
    $("simAmountVal").textContent = fmtINR(+$("simAmount").value);
    $("simTenureVal").textContent = `${$("simTenure").value} years`;
  }
  function onSim() {
    paintSim();
    clearTimeout(simTimer);
    simTimer = setTimeout(async () => {
      const applicant = { ...lastProfile, loan_amount: +$("simAmount").value, tenure_years: +$("simTenure").value };
      try {
        const res = await fetch("/api/evaluate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ applicant }) });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const ev = await res.json();
        const cls = { ELIGIBLE: "v-ELIGIBLE", CONDITIONAL: "v-CONDITIONAL", NOT_ELIGIBLE: "v-NOT_ELIGIBLE" }[ev.status] || "";
        $("simOut").innerHTML = `<span class="verified ${cls}">${esc(VERDICT[ev.status] || ev.status)}</span><br>` +
          `EMI <b>${esc(fmtINR(ev.emi))}</b>/month · FOIR <b>${ev.foir != null ? Math.round(ev.foir * 100) + "%" : "–"}</b>` +
          (ev.status !== "ELIGIBLE" && ev.max_eligible_amount ? ` · max <b>${esc(fmtINR(ev.max_eligible_amount))}</b>` : "");
      } catch (e) { $("simOut").textContent = "Couldn't recalculate right now (" + e.message + ")."; }
    }, 250);
  }
  $("simAmount").addEventListener("input", onSim);
  $("simTenure").addEventListener("input", onSim);

  // ------------------------------------------------------------ send / reset
  async function send(text, langOverride) {
    text = (text || input.value).trim();
    if (!text || busy) return;
    busy = true; sendBtn.disabled = true;
    input.value = ""; autosize();
    $("quick").innerHTML = "";
    addMessage("user", text);
    const typing = addTyping();
    try {
      const res = await fetch("/api/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, message: text, language: langOverride || langSelect.value }),
      });
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try { const j = await res.json(); if (typeof j.detail === "string") detail = j.detail; } catch {}
        throw new Error(detail);
      }
      const r = await res.json();
      sessionId = r.session_id;
      typing.remove();
      const src = r.reply_source === "genai+rules-template" ? "AI + rules" : r.mode === "genai" ? "AI" : "rules";
      addMessage("bot", r.reply, `${src} · ${(r.latency_ms / 1000).toFixed(1)} s`, r.verified_verdict);
      updateDashboard(r);
      if (tts) speak(r.reply, r.language);
    } catch (e) {
      typing.remove();
      addMessage("bot", "Sorry — " + e.message);
      renderQuick(lastEval ? null : "loan_type", lastProfile, lastEval);
    } finally {
      busy = false; sendBtn.disabled = false; input.focus();
    }
  }
  form.addEventListener("submit", (e) => { e.preventDefault(); send(); });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
  function autosize() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 140) + "px"; }
  input.addEventListener("input", autosize);

  async function resetAll() {
    if (sessionId) {
      try { await fetch("/api/reset", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId }) }); } catch {}
    }
    sessionId = null; lastProfile = {}; lastEval = null; lastMissing = [];
    messagesEl.querySelectorAll(".msg").forEach((m, i) => { if (i > 0) m.remove(); });
    $("profileList").innerHTML = ""; $("profileProgress").textContent = "";
    $("statusPill").className = "pill pill-idle"; $("statusPill").textContent = "Awaiting details";
    $("resultLabel").textContent = "Your eligible amount"; $("resultAmount").textContent = "—";
    $("resultSub").textContent = "Share your details and your eligibility appears here.";
    $("gaugeScore").textContent = "–"; $("gaugeFill").style.strokeDashoffset = "157";
    ["kpiEmi", "kpiRate", "kpiTenure", "kpiFoir"].forEach((id) => ($(id).textContent = "–"));
    $("checksList").innerHTML = ""; $("checksEmpty").hidden = false;
    ["stepsCard", "docsCard", "simCard"].forEach((id) => ($(id).hidden = true));
    selectProduct(null);
    updateStepper({}, null);
    renderQuick("loan_type", {}, null);
  }
  resetBtn.addEventListener("click", resetAll);

  // ------------------------------------------------------------ voice (Sarvam via backend, browser fallback)
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  let rec = null, recorder = null;
  async function startSarvamRecording() {
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
    catch { addMessage("bot", "Microphone permission was denied."); return; }
    const chunks = [];
    recorder = new MediaRecorder(stream);
    recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    recorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      micBtn.classList.remove("listening"); recorder = null;
      const blob = new Blob(chunks, { type: chunks[0]?.type || "audio/webm" });
      input.placeholder = "Transcribing…";
      try {
        const res = await fetch("/api/stt", { method: "POST", headers: { "Content-Type": blob.type }, body: blob });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const { transcript, language_code } = await res.json();
        const spoken = (language_code || "").split("-")[0];
        const known = [...langSelect.options].map((o) => o.value);
        const lang = langSelect.value === "auto" && known.includes(spoken) ? spoken : undefined;
        if (transcript && transcript.trim()) { input.value = transcript.trim(); autosize(); send(undefined, lang); }
      } catch (e) { addMessage("bot", "Sorry, I couldn't hear that clearly. Please try again or type. (" + e.message + ")"); }
      finally { input.placeholder = "Type your message…"; }
    };
    recorder.start();
    micBtn.classList.add("listening");
    setTimeout(() => recorder && recorder.state === "recording" && recorder.stop(), 20000);
  }
  micBtn.addEventListener("click", () => {
    if (voiceEngine === "sarvam") { if (recorder) recorder.stop(); else startSarvamRecording(); return; }
    if (!SR) return;
    if (rec) { rec.stop(); return; }
    rec = new SR();
    const v = langSelect.value;
    rec.lang = v === "hinglish" ? "hi-IN" : ["auto", "en"].includes(v) ? "en-IN" : `${v}-IN`;
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

  let currentAudio = null;
  ttsBtn.addEventListener("click", () => {
    tts = !tts; ttsBtn.setAttribute("aria-pressed", String(tts)); ttsBtn.textContent = tts ? "🔊" : "🔈";
    if (!tts) { window.speechSynthesis?.cancel(); currentAudio?.pause(); }
  });
  async function speak(text, lang) {
    if (voiceEngine === "sarvam") {
      try {
        currentAudio?.pause();
        const res = await fetch("/api/tts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, language: lang }) });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const { audio_wav_base64 } = await res.json();
        currentAudio = new Audio("data:audio/wav;base64," + audio_wav_base64);
        if (tts) currentAudio.play();
        return;
      } catch (e) { console.warn("Sarvam TTS failed, using browser voice", e); }
    }
    if (!window.speechSynthesis) return;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text.replace(/[•✅🟡🔴→☐*#_]/g, " ").replace(/\s+/g, " ").slice(0, 900));
    u.lang = /[ऀ-ॿ]/.test(text) || lang === "hi" ? "hi-IN" : "en-IN";
    window.speechSynthesis.speak(u);
  }

  // ------------------------------------------------------------ chat / quick-form tabs
  let currentMode = null, currentModel = null;
  function showTab(which) {
    const form = which === "form";
    $("tabChat").setAttribute("aria-selected", String(!form));
    $("tabForm").setAttribute("aria-selected", String(form));
    $("chatPanel").hidden = form;
    $("formPanel").hidden = !form;
    if (form) $("fAmount").focus(); else input.focus();
  }
  $("tabChat").addEventListener("click", () => showTab("chat"));
  $("tabForm").addEventListener("click", () => showTab("form"));

  function syncFormFields() {
    const type = $("fType").value;
    document.querySelectorAll("#quickForm [data-show]").forEach((el) => { el.hidden = !el.dataset.show.split(" ").includes(type); });
    const [lo, hi] = PRODUCT[type].tenure;
    $("fTenure").min = String(lo); $("fTenure").max = String(hi); $("fTenure").placeholder = String(PRODUCT[type].tenures[1]);
    selectProduct(type);
  }
  $("fType").addEventListener("change", syncFormFields);
  document.querySelectorAll("#quickForm .fmt").forEach((hint) => {
    const field = $(hint.dataset.for);
    field.addEventListener("input", () => { hint.textContent = field.value ? fmtINR(+field.value) : ""; });
  });
  // Product tabs also pre-select the form's loan type
  document.querySelectorAll(".product").forEach((b) => b.addEventListener("click", () => { $("fType").value = b.dataset.type; syncFormFields(); }));

  function formApplicant() {
    const type = $("fType").value, num = (id) => ($(id).value === "" ? null : +$(id).value);
    const a = { loan_type: type, loan_amount: num("fAmount"), tenure_years: num("fTenure"), age: num("fAge") };
    if (type === "education") {
      Object.assign(a, { study_abroad: $("fAbroad").value === "true", co_applicant_income: num("fCoIncome"),
        co_applicant_credit_score: $("fCoScore").value === "unknown" ? "unknown" : +$("fCoScore").value, co_applicant_existing_emi: num("fCoEmi") ?? 0 });
    } else {
      Object.assign(a, { employment_type: $("fEmp").value, monthly_income: num("fIncome"),
        credit_score: $("fScore").value === "unknown" ? "unknown" : +$("fScore").value, existing_emi: num("fEmi") ?? 0 });
      if (type === "home") a.property_value = num("fProperty");
      if (type === "auto") a.vehicle_price = num("fVehicle");
    }
    for (const k of Object.keys(a)) if (a[k] === null) delete a[k];
    return a;
  }

  function chatSentence(a) {
    const parts = [`I want a ${PRODUCT[a.loan_type].label.toLowerCase()} of ${fmtINR(a.loan_amount)} for ${a.tenure_years} years.`, `I am ${a.age}.`];
    if (a.loan_type === "education") {
      parts.push(`The course is ${a.study_abroad ? "abroad" : "in India"}. My father earns ${a.co_applicant_income} per month,`,
        a.co_applicant_credit_score === "unknown" ? "his credit score is unknown," : `his credit score is ${a.co_applicant_credit_score},`,
        a.co_applicant_existing_emi ? `he pays ${a.co_applicant_existing_emi} EMI.` : "he has no EMIs.");
    } else {
      parts.push(a.employment_type === "self_employed" ? "I am self-employed," : a.employment_type === "not_employed" ? "I am not working," : "I am salaried,",
        `my salary is ${a.monthly_income} per month,`, a.credit_score === "unknown" ? "I don't know my credit score," : `my credit score is ${a.credit_score},`,
        a.existing_emi ? `I pay ${a.existing_emi} EMI.` : "no EMIs.");
      if (a.property_value) parts.push(`The property is worth ${fmtINR(a.property_value)}.`);
      if (a.vehicle_price) parts.push(`On-road price is ${fmtINR(a.vehicle_price)}.`);
    }
    return parts.join(" ");
  }

  $("quickForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const out = $("formResult"), btn = $("quickForm").querySelector(".btn-cta");
    const required = ["fAmount", "fTenure", "fAge"].concat($("fType").value === "education" ? ["fCoIncome"] : ["fIncome"])
      .concat($("fType").value === "home" ? ["fProperty"] : $("fType").value === "auto" ? ["fVehicle"] : []);
    const empty = required.filter((id) => $(id).value === "");
    if (empty.length) { out.hidden = false; out.textContent = "Please fill in the highlighted fields."; $(empty[0]).focus(); return; }
    const applicant = formApplicant();
    btn.disabled = true;
    const started = performance.now();
    try {
      const res = await fetch("/api/evaluate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ applicant }) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const ev = await res.json();
      const ms = Math.round(performance.now() - started);
      if (ev.status === "INCOMPLETE") {
        out.hidden = false;
        out.textContent = "Some values look off: " + (ev.invalid_fields || ev.missing_fields || []).map((k) => (FIELD_LABELS[k] || k).toLowerCase()).join(", ") + ". Please check them.";
        return;
      }
      updateDashboard({ evaluation: ev, profile: applicant, missing_fields: [], documents: ev.documents || [], latency_ms: ms,
        pii_masked: [], language: "en", mode: currentMode, model: currentModel, next_field: null });
      out.hidden = false;
      out.innerHTML = `<span class="verified v-${esc(ev.status)}">🔒 ${esc(VERDICT[ev.status] || ev.status)}</span><div>${esc(ev.summary)}</div>` +
        (ev.improvements.length ? `<ul>${ev.improvements.slice(0, 2).map((s) => `<li>${esc(s)}</li>`).join("")}</ul>` : "") +
        `<button type="button" class="link-btn" id="discussBtn">💬 Discuss this result in chat →</button>`;
      $("discussBtn").addEventListener("click", () => { showTab("chat"); send(chatSentence(applicant)); });
    } catch (err) {
      out.hidden = false; out.textContent = "Couldn't check right now (" + err.message + "). Please try again.";
    } finally { btn.disabled = false; }
  });

  // ------------------------------------------------------------ lender comparison (simulated panel)
  async function refreshLenders(profile) {
    try {
      const res = await fetch("/api/lenders/compare", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ applicant: profile }) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const r = await res.json();
      $("lendersList").innerHTML = r.offers.map((o) => {
        const best = o.lender_id === r.best_lender_id;
        const line = o.full_amount ? `EMI ${fmtINR(o.emi)}/mo · fee ${fmtINR(o.processing_fee)}`
          : o.status === "CONDITIONAL" ? `Up to ${fmtINR(o.max_eligible_amount)}` : "Not eligible";
        const why = !o.full_amount && o.top_reason ? `<div class="why">${esc(o.top_reason)}</div>` : "";
        return `<div class="lender${best ? " best" : ""}"><div><b>${esc(o.lender)}</b>${best ? '<span class="best-badge">BEST</span>' : ""}<br>` +
          `<small>${esc(o.type)} · ${esc(line)}</small></div><div class="rate">${o.interest_rate}%</div>${why}</div>`;
      }).join("");
      $("lendersCard").hidden = false;
    } catch (e) { $("lendersCard").hidden = true; }
  }

  // ------------------------------------------------------------ simulated bureau + Account Aggregator autofill
  $("fetchBtn").addEventListener("click", async () => {
    const last4 = $("fMobile4").value.trim(), out = $("fetchOut");
    if (!/^[0-9]{4}$/.test(last4)) { out.textContent = "Enter the last 4 digits of your mobile number."; return; }
    if (!$("fConsent").checked) { out.textContent = "Please tick the consent box first."; return; }
    const body = JSON.stringify({ consent: true, mobile_last4: last4 }), headers = { "Content-Type": "application/json" };
    out.textContent = "Fetching…";
    try {
      const [cb, aa] = await Promise.all([
        fetch("/api/sim/bureau/soft-pull", { method: "POST", headers, body }).then((r) => r.json()),
        fetch("/api/sim/aa/income", { method: "POST", headers, body }).then((r) => r.json()),
      ]);
      if ($("fType").value === "education") $("fType").value = "personal", syncFormFields();
      $("fEmp").value = aa.employment_type;
      $("fIncome").value = String(Math.round(aa.avg_monthly_income)); $("fIncome").dispatchEvent(new Event("input"));
      $("fEmi").value = String(cb.total_monthly_emi);
      let opt = [...$("fScore").options].find((o) => o.value === String(cb.credit_score));
      if (!opt) { opt = new Option(`${cb.credit_score} (fetched)`, String(cb.credit_score)); $("fScore").add(opt, 0); }
      $("fScore").value = String(cb.credit_score);
      out.textContent = `Filled from simulated bureau (score ${cb.credit_score}, ${cb.active_loans.length} active loan(s), report ${cb.report_id}) ` +
        `and Account Aggregator (avg income ${fmtINR(aa.avg_monthly_income)} over 6 months). Simulated data only.`;
    } catch (e) { out.textContent = "Couldn't fetch right now (" + e.message + ")."; }
  });

  // ------------------------------------------------------------ bank statement (live, in-memory analysis)
  async function analyzeStatement(file) {
    if (file.size > 5 * 1024 * 1024) throw new Error("File is larger than 5 MB");
    const type = file.type || (file.name.toLowerCase().endsWith(".csv") ? "text/csv" : "application/pdf");
    const qs = new URLSearchParams({ consent: "true", ...(sessionId ? { session_id: sessionId } : {}) });
    const res = await fetch(`/api/statement/analyze?${qs}`, { method: "POST", headers: { "Content-Type": type }, body: file });
    const j = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof j.detail === "string" ? j.detail : `HTTP ${res.status}`);
    return j;
  }
  const stmtSummary = (a) => `${a.months_covered} months read · ${a.income_type === "salaried" ? "salary" : "income"} ≈ ${fmtINR(a.avg_monthly_income)}/month · ` +
    `EMIs ≈ ${fmtINR(a.avg_monthly_emi)}/month · ${a.bounced_payments} bounced payment(s)`;

  $("attachBtn").addEventListener("click", () => {
    if (!confirm("Read your bank statement to verify income and EMIs?\n\nIt is analysed in memory and never stored; only monthly totals are used.")) return;
    $("stmtFile").click();
  });
  $("stmtFile").addEventListener("change", async () => {
    const file = $("stmtFile").files[0];
    $("stmtFile").value = "";
    if (!file) return;
    addMessage("user", `📎 ${file.name}`);
    const typing = addTyping();
    try {
      const a = await analyzeStatement(file);
      sessionId = a.session_id || sessionId;
      typing.remove();
      addMessage("bot", `📄 Statement analysed (${a.period}). ${stmtSummary(a)}.\nThe file wasn't stored.`);
      send(`My bank statement shows ${a.income_type === "salaried" ? "a salary" : "income"} of ${Math.round(a.avg_monthly_income)} per month and ` +
        `${a.avg_monthly_emi ? `EMIs of ${Math.round(a.avg_monthly_emi)} per month` : "no EMIs"}. I am ${a.income_type === "salaried" ? "salaried" : "self-employed"}.`);
    } catch (e) { typing.remove(); addMessage("bot", "Sorry — " + e.message); }
  });

  $("fStmt").addEventListener("change", async () => {
    const file = $("fStmt").files[0], out = $("stmtOut");
    if (!file) return;
    out.textContent = "Analysing…";
    try {
      const a = await analyzeStatement(file);
      if ($("fType").value === "education") { $("fType").value = "personal"; syncFormFields(); }
      $("fEmp").value = a.income_type;
      $("fIncome").value = String(Math.round(a.avg_monthly_income)); $("fIncome").dispatchEvent(new Event("input"));
      $("fEmi").value = String(Math.round(a.avg_monthly_emi));
      out.textContent = `✓ Verified from statement: ${stmtSummary(a)}. File not stored.`;
    } catch (e) { out.textContent = "Couldn't read it: " + e.message; }
    finally { $("fStmt").value = ""; }
  });

  // ------------------------------------------------------------ boot
  (async () => {
    try {
      const h = await (await fetch("/api/health")).json();
      setModeBadge(h.mode, h.model);
      voiceEngine = h.voice === "sarvam" && window.MediaRecorder ? "sarvam" : "browser";
      micBtn.title = voiceEngine === "sarvam" ? "Speak — tap again to stop" : "Speak";
      if (voiceEngine === "browser" && !SR) { micBtn.disabled = true; micBtn.title = "Voice input needs Chrome or Edge"; }
    } catch (e) { console.error(e); }
    updateStepper({}, null);
    renderQuick("loan_type", {}, null);
    syncFormFields();
    selectProduct(null);
    const q = new URLSearchParams(location.search).get("q");  // hand-off from the landing page's EMI planner
    if (q) { input.value = q.slice(0, 500); autosize(); }
    input.focus();
  })();
})();
