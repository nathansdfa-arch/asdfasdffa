// Small shared screen helpers: toasts, guard results, sounds.

import { escapeHtml } from "./format.js";
import { store } from "./store.js";

export function toast(text, kind = "ok", detail = "") {
  const box = document.getElementById("toasts");
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.innerHTML = `<div>${escapeHtml(text)}</div>${detail ? `<div class="rule">${escapeHtml(detail)}</div>` : ""}`;
  box.appendChild(el);
  setTimeout(() => el.remove(), kind === "ok" ? 3500 : 8000);
}

// Shows what the risk guard decided about an order, in plain English.
export function showResult(result, okText) {
  if (result.ok) toast(okText || result.message, "ok", result.decision?.rule === "Rule 2: always let the owner out" ? "Risk-reducing: always allowed" : "");
  else toast(`Blocked: ${result.message}`, "blocked", result.decision?.rule || "");
  if (!result.ok) beep("danger");
}

let audio = null;
export function beep(level) {
  if (!store.settings.alert_sounds) return;
  try {
    audio = audio || new AudioContext();
    const osc = audio.createOscillator();
    const gain = audio.createGain();
    osc.frequency.value = level === "danger" ? 440 : 660;
    gain.gain.value = 0.08;
    osc.connect(gain).connect(audio.destination);
    osc.start();
    osc.stop(audio.currentTime + (level === "danger" ? 0.35 : 0.15));
  } catch (e) { /* sound not available */ }
}

export function h(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}
