// Number and time formatting. Times arrive in UTC and are shown in the owner's time zone.

import { store, market } from "./store.js";

export function decimalsFor(symbol) {
  const tick = market(symbol)?.tick_size ?? 0.01;
  const text = String(tick);
  return text.includes("e-") ? Number(text.split("e-")[1]) : (text.split(".")[1] || "").length;
}

export function price(value, symbol) {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  return Number(value).toLocaleString(undefined, { minimumFractionDigits: decimalsFor(symbol), maximumFractionDigits: decimalsFor(symbol) });
}

export function money(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  return Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function percent(value, digits = 0) {
  if (value === null || value === undefined) return "–";
  return `${(value * 100).toFixed(digits)}%`;
}

export function signed(value) {
  if (value === null || value === undefined) return "–";
  return (value > 0 ? "+" : "") + money(value);
}

function zone() { return store.settings.display_timezone || "UTC"; }

export function time(unixSeconds, withSeconds = false) {
  if (!unixSeconds) return "–";
  return new Date(unixSeconds * 1000).toLocaleString(undefined, {
    timeZone: zone(), month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    second: withSeconds ? "2-digit" : undefined, hour12: false,
  });
}

// Chart axis labels in the owner's time zone.
export function chartTime(unixSeconds, kind) {
  const d = new Date(unixSeconds * 1000);
  const opts = { timeZone: zone(), hour12: false };
  if (kind === "year") return d.toLocaleString(undefined, { ...opts, year: "numeric" });
  if (kind === "month") return d.toLocaleString(undefined, { ...opts, month: "short" });
  if (kind === "day") return d.toLocaleString(undefined, { ...opts, day: "numeric", month: "short" });
  return d.toLocaleString(undefined, { ...opts, hour: "2-digit", minute: "2-digit" });
}

export function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
