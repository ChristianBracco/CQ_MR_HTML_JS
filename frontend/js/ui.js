/**
 * ui.js — UI utility functions for MRI QC
 */
"use strict";

const UI = {
  showStep(n) {
    document.querySelectorAll(".step-panel").forEach(p => p.classList.remove("active"));
    const panel = document.getElementById(`step-${n}`);
    if (panel) panel.classList.add("active");

    document.querySelectorAll(".step-btn").forEach(btn => {
      const s = parseInt(btn.dataset.step);
      btn.classList.remove("active", "done");
      if (s === n) btn.classList.add("active");
      else if (s < n) btn.classList.add("done");
    });
    AppState.currentStep = n;
  },

  setStatus(msg) {
    const el = document.getElementById("status-msg");
    if (el) el.textContent = msg;
  },

  setApiStatus(ok) {
    const badge = document.getElementById("api-status");
    if (!badge) return;
    badge.textContent = ok ? "API ✓" : "API ✗";
    badge.className = ok ? "badge badge-ok" : "badge badge-red";
  },

  show(el) {
    if (typeof el === "string") el = document.getElementById(el);
    if (el) el.classList.remove("hidden");
  },

  hide(el) {
    if (typeof el === "string") el = document.getElementById(el);
    if (el) el.classList.add("hidden");
  },

  fmt(v, decimals = 2) {
    if (v === null || v === undefined) return "–";
    const n = parseFloat(v);
    if (isNaN(n)) return "–";
    return n.toFixed(decimals);
  },

  passIcon(passed) {
    if (passed === null || passed === undefined) return '<span style="color:var(--text-muted)">–</span>';
    return passed
      ? '<span style="color:var(--accent-green);font-weight:700;">✓ PASS</span>'
      : '<span style="color:var(--accent-red);font-weight:700;">✗ FAIL</span>';
  },
};
