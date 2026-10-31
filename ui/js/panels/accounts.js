// Accounts: paper and broker accounts, their risk rules, prop firm profiles,
// the evaluation simulator, live switching, and the prop firm signup buttons.

import { del, get, post, put } from "../api.js";
import { activeAccount, refreshAccounts, setActiveAccount, store } from "../store.js";
import { escapeHtml, money, percent } from "../format.js";
import { toast } from "../ui.js";

let profiles = [];
let links = [];

export async function renderAccounts(el, ctx) {
  if (!profiles.length) profiles = await get("/api/profiles").catch(() => []);
  if (!links.length) links = await get("/api/prop-links").catch(() => []);
  const active = activeAccount();
  el.innerHTML = `
    ${store.accounts.map((a) => accountCard(a, a.id === active?.id)).join("")}
    <div class="section">
      <h3>New account</h3>
      <div class="stack">
        <div class="grid2">
          <label class="field">Name<input id="n-name" type="text" placeholder="e.g. Tradeify eval"></label>
          <label class="field">Type<select id="n-broker"><option value="paper">Paper (practice money)</option><option value="rithmic">Rithmic (futures)</option><option value="mt5">MetaTrader 5 (forex, CFDs)</option><option value="bybit">Bybit (crypto)</option></select></label>
          <label class="field">Starting balance<input id="n-balance" type="number" value="25000"></label>
          <label class="field">Safety buffer ($)<input id="n-buffer" type="number" value="100"></label>
        </div>
        <label class="field">Prop firm rules<select id="n-profile"><option value="">None (no prop firm)</option>${profiles.map((p) => `<option value="${p.id}">${escapeHtml(p.firm)} · ${escapeHtml(p.plan)}${p.confirmed_by_owner ? "" : " (numbers not confirmed)"}</option>`).join("")}</select></label>
        <p class="muted">Broker accounts trade on paper until you deliberately switch them to live.</p>
        <button class="btn primary" id="n-create">Create account</button>
      </div>
    </div>
    <div class="section">
      <h3>Prop firms</h3>
      <div class="row">${links.map((f) => `<a class="pill-link" href="${escapeHtml(f.url)}" target="_blank" rel="noopener">Set up ${escapeHtml(f.name)} account<small>${escapeHtml(f.market)} · ${escapeHtml(f.automation)}</small></a>`).join("")}</div>
      <p class="muted">Opens the firm's own website. The app never handles payment. Edit these links in config/prop_firm_links.json.</p>
    </div>`;

  el.querySelector("#n-create").addEventListener("click", async () => {
    try {
      const account = await post("/api/accounts", {
        name: el.querySelector("#n-name").value || "New account", broker: el.querySelector("#n-broker").value,
        starting_balance: Number(el.querySelector("#n-balance").value), safety_buffer: Number(el.querySelector("#n-buffer").value),
        profile_id: el.querySelector("#n-profile").value || null,
      });
      await refreshAccounts();
      setActiveAccount(account.id);
      toast(`Created ${account.name}`);
    } catch (problem) { toast(problem.message, "blocked"); }
  });

  el.querySelectorAll("[data-account]").forEach((card) => wireCard(card, ctx));
}

function accountCard(a, isActive) {
  const n = a.numbers || {};
  const usedClass = n.used >= 1 ? "danger" : n.used >= 0.7 ? "warn" : "";
  const r = a.rules;
  const evaluation = a.evaluation;
  return `
  <div class="section ${isActive ? "glow" : ""}" data-account="${a.id}" style="${isActive ? "border-color:var(--accent)" : ""}">
    <div class="row spread">
      <div class="row"><strong>${escapeHtml(a.name)}</strong><span class="badge ${a.mode === "LIVE" ? "live" : "paper"}">${a.mode}</span>
        <span class="muted">${a.broker === "paper" ? "paper" : escapeHtml(a.broker)}${a.profile ? " · " + escapeHtml(a.profile.firm) : ""}</span></div>
      ${isActive ? '<span class="muted">active</span>' : '<button class="btn small" data-act="use">Use this account</button>'}
    </div>
    ${a.profile_problem ? `<div class="message warn" style="margin-top:6px">${escapeHtml(a.profile_problem)}</div>` : ""}
    ${!a.broker_connected && a.broker !== "paper" && a.mode === "LIVE" ? `<div class="message blocked">${escapeHtml(a.broker_status)}</div>` : ""}
    ${n.halted ? `<div class="message blocked">Halted: ${escapeHtml(n.halt_reason)} <button class="btn small" data-act="resume">Resume account</button></div>` : ""}
    ${n.failed ? `<div class="message blocked">The drawdown floor was touched. This account has failed its rules.</div>` : ""}
    ${n.balance_mismatch ? `<div class="message blocked">The app's balance and the broker's disagree. Check the broker, then <button class="btn small" data-act="accept">Accept broker balance</button></div>` : ""}
    <div class="grid3" style="margin-top:8px">
      <div><div class="muted">Balance</div><div class="num">${money(n.balance)}</div></div>
      <div><div class="muted">Equity</div><div class="num">${money(n.equity)}</div></div>
      <div><div class="muted">Loss room used</div><div class="num">${n.used !== undefined ? percent(n.used) : "–"}</div><div class="meter ${usedClass}"><div style="width:${Math.min(100, (n.used || 0) * 100)}%"></div></div></div>
      ${n.floor !== undefined ? `<div><div class="muted">Floor</div><div class="num">${money(n.floor)}${n.floor_locked ? " 🔒" : ""}</div></div><div><div class="muted">Room left</div><div class="num">${money(n.room_left)}</div></div><div><div class="muted">High-water mark</div><div class="num">${money(n.high_water_mark)}</div></div>` : ""}
      ${n.daily_limit !== undefined ? `<div><div class="muted">Loss today</div><div class="num">${money(n.loss_today)}</div></div><div><div class="muted">Daily limit</div><div class="num">${money(n.daily_limit)}</div></div>` : ""}
    </div>
    ${evaluation ? `<div style="margin-top:8px"><div class="row spread"><span>Evaluation: <strong>${escapeHtml(evaluation.status)}</strong></span><span class="num">${money(evaluation.profit)} / ${money(evaluation.target)}</span></div>
      <div class="progress"><div style="width:${evaluation.progress}%"></div></div><div class="muted">${escapeHtml(evaluation.message)} Trading days: ${evaluation.days_traded}${evaluation.min_trading_days ? " of " + evaluation.min_trading_days : ""}.</div></div>` : ""}
    <details style="margin-top:8px"><summary>Risk rules</summary>
      <div class="grid2" style="margin-top:6px">
        ${ruleField("Max daily loss ($)", "max_daily_loss", r.max_daily_loss)}
        ${ruleField("Drawdown amount ($)", "drawdown_amount", r.drawdown_amount)}
        <label class="field">Drawdown method<select data-rule="drawdown_method">${["intraday", "end_of_day", "static"].map((m) => `<option ${m === r.drawdown_method ? "selected" : ""}>${m}</option>`).join("")}</select></label>
        ${ruleField("Floor locks at ($)", "drawdown_lock", r.drawdown_lock)}
        ${ruleField("Safety buffer ($)", "safety_buffer", r.safety_buffer)}
        ${ruleField("Max position size", "max_position_size", r.max_position_size)}
        ${ruleField("Max total contracts/lots", "max_total_quantity", r.max_total_quantity)}
        ${ruleField("Trades per day", "daily_trade_limit", r.daily_trade_limit)}
        <label class="field">Allowed hours (e.g. 08:30-15:00)<input type="text" data-rule="allowed_hours" value="${escapeHtml(r.allowed_hours || "")}"></label>
        <label class="field">Hours time zone<input type="text" data-rule="hours_timezone" value="${escapeHtml(r.hours_timezone)}"></label>
        <label class="field">Day resets at<input type="text" data-rule="reset_time" value="${escapeHtml(r.reset_time)}"></label>
        <label class="field">Reset time zone<input type="text" data-rule="reset_timezone" value="${escapeHtml(r.reset_timezone)}"></label>
        ${ruleField("Profit target ($)", "profit_target", r.profit_target)}
        ${ruleField("Orders per minute before a script pauses", "max_orders_per_minute_per_script", r.max_orders_per_minute_per_script)}
        <label class="field">Every order needs a stop<select data-rule="require_stop_loss"><option value="true" ${r.require_stop_loss ? "selected" : ""}>Yes</option><option value="false" ${r.require_stop_loss ? "" : "selected"}>No</option></select></label>
        <label class="field">At 100%: close all and halt<select data-rule="auto_flatten_at_limit"><option value="true" ${r.auto_flatten_at_limit ? "selected" : ""}>Yes</option><option value="false" ${r.auto_flatten_at_limit ? "" : "selected"}>No</option></select></label>
      </div>
      <button class="btn small primary" data-act="save-rules" style="margin-top:6px">Save rules</button>
      ${a.profile ? `<p class="muted">Rule page: <a href="${escapeHtml(a.profile.rule_page)}" target="_blank" rel="noopener">${escapeHtml(a.profile.rule_page || "not set")}</a>. Firm numbers come from config/prop_firms.json; confirm every one against the firm's current page.</p>` : ""}
    </details>
    ${a.broker !== "paper" ? brokerSection(a) : ""}
    <div class="row" style="margin-top:8px">
      ${a.mode === "PAPER" ? '<button class="btn small" data-act="reset">Reset paper balance</button>' : ""}
      <button class="btn small" data-act="delete">Remove</button>
    </div>
  </div>`;
}

function ruleField(label, key, value) {
  return `<label class="field">${label}<input type="number" data-rule="${key}" value="${value ?? ""}" placeholder="no limit"></label>`;
}

function brokerSection(a) {
  const names = a.broker === "bybit" ? ["api_key", "api_secret"] : a.broker === "mt5" ? ["password"] : ["password"];
  const settings = a.broker === "mt5" ? ["login", "server", "terminal_path", "symbol_suffix"] : a.broker === "bybit" ? ["testnet", "account_type"] : ["user", "system_name", "gateway"];
  return `<details style="margin-top:8px"><summary>Broker connection</summary>
    <div class="stack" style="margin-top:6px">
      <div class="muted">Status: ${escapeHtml(a.broker_status)}</div>
      ${a.broker === "rithmic" ? `<div class="message warn">Rithmic needs API access and approval from Rithmic before it can connect. See NEEDS_NATHAN.md.</div>` : ""}
      <div class="grid2">${settings.map((k) => `<label class="field">${k.replace("_", " ")}<input type="text" data-setting="${k}" value="${escapeHtml(String(a.broker_settings?.[k] ?? (k === "testnet" ? "true" : "")))}"></label>`).join("")}</div>
      <button class="btn small" data-act="save-broker">Save connection settings</button>
      <div class="grid2">${names.map((k) => `<label class="field">${k.replace("_", " ")} ${a.secrets?.[k] ? "(saved)" : ""}<input type="password" data-secret="${k}" placeholder="${a.secrets?.[k] ? "•••••• saved" : "enter to save"}"></label>`).join("")}</div>
      <button class="btn small" data-act="save-secrets">Save to Windows Credential Manager</button>
      <div class="row"><button class="btn small" data-act="connect">Test connection</button>
        ${a.mode === "LIVE" ? '<button class="btn small" data-act="paper">Switch back to PAPER</button>' : '<button class="btn small" data-act="live" style="border-color:var(--safe-live)">Switch to LIVE…</button>'}</div>
    </div></details>`;
}

function wireCard(card, ctx) {
  const id = card.dataset.account;
  const run = async (fn, okText) => {
    try { await fn(); if (okText) toast(okText); } catch (problem) { toast(problem.message, "blocked"); }
    await refreshAccounts();
  };
  const on = (act, fn) => card.querySelector(`[data-act=${act}]`)?.addEventListener("click", fn);
  on("use", () => setActiveAccount(id));
  on("resume", () => run(() => post(`/api/accounts/${id}/resume`), "Account resumed"));
  on("accept", () => run(() => post(`/api/accounts/${id}/accept-balance`), "Broker balance accepted"));
  on("reset", () => { if (confirm("Reset this paper account to its starting balance? Open paper positions are wiped.")) run(() => post(`/api/accounts/${id}/reset`), "Paper account reset"); });
  on("delete", () => { if (confirm("Remove this account from the app?")) run(() => del(`/api/accounts/${id}`), "Account removed"); });
  on("save-rules", () => {
    const rules = {};
    card.querySelectorAll("[data-rule]").forEach((input) => {
      const key = input.dataset.rule;
      let value = input.value.trim();
      if (input.tagName === "SELECT" && (value === "true" || value === "false")) value = value === "true";
      else if (input.type === "number") value = value === "" ? null : Number(value);
      else if (value === "" && key === "allowed_hours") value = null;
      rules[key] = value;
    });
    run(() => put(`/api/accounts/${id}`, { rules }), "Rules saved");
  });
  on("save-broker", () => {
    const settings = {};
    card.querySelectorAll("[data-setting]").forEach((i) => { settings[i.dataset.setting] = i.dataset.setting === "testnet" ? i.value.trim() !== "false" : i.value.trim(); });
    run(() => put(`/api/accounts/${id}`, { broker_settings: settings }), "Connection settings saved");
  });
  on("save-secrets", () => run(async () => {
    for (const input of card.querySelectorAll("[data-secret]")) {
      if (input.value) await post(`/api/accounts/${id}/secret`, { name: input.dataset.secret, value: input.value });
    }
  }, "Saved securely"));
  on("connect", () => run(async () => {
    const result = await post(`/api/accounts/${id}/connect`);
    toast(result.status, result.ok ? "ok" : "blocked");
  }));
  on("paper", () => run(() => post(`/api/accounts/${id}/disable-live`), "Back on PAPER"));
  on("live", () => {
    const account = store.accounts.find((a) => a.id === id);
    const phrase = prompt(`LIVE trading uses real money.\n\nThe risk guard still checks every order, but losses are real.\nTo continue, type exactly:\n\nLIVE ${account.name}`);
    if (phrase === null) return;
    run(() => post(`/api/accounts/${id}/enable-live`, { confirm: phrase }), `${account.name} is now LIVE`);
  });
}
