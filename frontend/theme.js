/* Shared theme toggle — CSP-safe, no inline handlers. Loaded by landing + chat. */
(() => {
  const root = document.documentElement;
  let saved = null;
  try { saved = localStorage.getItem("loanmitra-theme"); } catch { /* private mode */ }
  if (saved === "light" || saved === "dark") root.dataset.theme = saved;
  window.addEventListener("DOMContentLoaded", () => {
    const btn = document.getElementById("themeBtn");
    if (!btn) return;
    const paint = () => {
      const dark = (root.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")) === "dark";
      btn.setAttribute("aria-pressed", String(dark));
      btn.querySelectorAll(".sun,.moon").forEach((el) => { el.hidden = dark ? el.classList.contains("sun") : el.classList.contains("moon"); });
    };
    btn.addEventListener("click", () => {
      const dark = (root.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")) === "dark";
      root.dataset.theme = dark ? "light" : "dark";
      try { localStorage.setItem("loanmitra-theme", dark ? "light" : "dark"); } catch { /* ignore */ }
      paint();
    });
    paint();
  });
})();
