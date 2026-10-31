// Alerts and the risk guard log: every decision, the rule that decided it, and the numbers.

import { get } from "../api.js";
import { store } from "../store.js";
import { escapeHtml, time as fmtTime } from "../format.js";

export async function renderLog(el) {
  const [alerts, decisions] = await Promise.all([get("/api/alerts?limit=50"), get("/api/guard-log?limit=150")]);
  const names = Object.fromEntries(store.accounts.map((a) => [a.id, a.name]));
  el.innerHTML = `
    <div class="section"><h3>Alerts</h3>
      ${alerts.length ? alerts.map((a) => `<div class="row" style="padding:3px 0"><span class="badge ${a.level === "danger" ? "danger" : a.level === "warning" ? "warn" : "paper"}">${escapeHtml(a.level)}</span><span class="muted num">${fmtTime(a.time)}</span><span>${escapeHtml(a.message)}</span></div>`).join("") : '<div class="muted">No alerts yet.</div>'}
    </div>
    <div class="section"><h3>Risk guard decisions</h3>
      <table class="data"><tr><th>Time</th><th>What</th><th>Result</th></tr>
      ${decisions.map((d) => `<tr><td class="num muted">${fmtTime(d.time, true)}</td>
        <td>${escapeHtml(d.action)} ${escapeHtml(d.symbol || "")}<div class="muted">${escapeHtml(names[d.account_id] || "")} · ${escapeHtml(d.source)}</div></td>
        <td><span class="badge ${d.approved ? "ok" : "danger"}">${d.approved ? "approved" : "blocked"}</span> ${escapeHtml(d.reason)}
          <div class="muted">${escapeHtml(d.rule)}</div>
          ${Object.keys(d.numbers || {}).length ? `<details><summary>Numbers used</summary><pre class="details">${escapeHtml(JSON.stringify(d.numbers, null, 1))}</pre></details>` : ""}</td></tr>`).join("")}
      </table></div>`;
}
