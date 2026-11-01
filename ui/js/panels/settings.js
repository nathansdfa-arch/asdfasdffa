// Settings: look and feel (theme proposals awaiting the owner's approval), time,
// feeds, sounds, security for remote access, backups and version.

import { get, post, put } from "../api.js";
import { store, changed } from "../store.js";
import { escapeHtml } from "../format.js";
import { THEMES, applyTheme } from "../themes.js";
import { toast } from "../ui.js";

export async function saveSetting(key, value) {
  try {
    await put(`/api/settings/${key}`, { value });
    store.settings[key] = value;
    applyTheme(store.settings);
    changed("settings");
  } catch (problem) { toast(problem.message, "blocked"); }
}

export async function renderSettings(el) {
  const s = store.settings;
  const local = ["127.0.0.1", "localhost"].includes(location.hostname);
  const [auth, backups, jarvis] = await Promise.all([get("/api/auth/status").catch(() => ({})), get("/api/backups").catch(() => []), get("/api/owner/jarvis").catch(() => ({}))]);
  const allowed = new Set(jarvis.allowed_account_ids || []);
  const paperAccounts = (store.accounts || []).filter((a) => a.mode === "PAPER");
  el.innerHTML = `
    <div class="section"><h3>Theme <span class="muted">(proposals: pick the one you like, or tell us to change them)</span></h3>
      <div class="grid2">${Object.entries(THEMES).map(([key, t]) => `
        <div class="theme-card ${s.theme === key ? "selected" : ""}" data-theme="${key}">
          <strong>${t.name}</strong>
          <div class="swatches">${[t.bg, t.panel, t.accent, t.up, t.down].map((c) => `<span style="background:${c}"></span>`).join("")}</div>
          <span class="muted">${t.note}</span>
        </div>`).join("")}</div>
    </div>
    <div class="section"><h3>Look</h3>
      <div class="grid2">
        ${colorField("Accent color", "accent_color")}
        ${colorField("Up candles", "candle_up_color")}
        ${colorField("Down candles", "candle_down_color")}
        <label class="field">Chart background<select data-key="chart_background">${["gradient", "solid", "animated", "plain"].map((o) => `<option ${s.chart_background === o ? "selected" : ""}>${o}</option>`).join("")}</select></label>
        <label class="field">Glow strength <input type="range" min="0" max="100" data-key="glow_strength" data-num value="${s.glow_strength}"></label>
        <label class="field">Effect intensity <input type="range" min="0" max="100" data-key="effect_intensity" data-num value="${s.effect_intensity}"></label>
        ${toggle("Visual effects", "effects_enabled")}
        ${toggle("Reduce motion", "reduce_motion")}
        ${toggle("Hollow up candles", "candle_hollow")}
        ${toggle("Glow on candles", "candle_glow")}
        <label class="field">Watchlist side<select data-key="watchlist_side">${["left", "right"].map((o) => `<option ${s.watchlist_side === o ? "selected" : ""}>${o}</option>`).join("")}</select></label>
      </div>
      <p class="muted">Safety colors (PAPER blue, LIVE red, warnings, blocks) never change with the theme.</p>
    </div>
    <div class="section"><h3>Time, feeds and sounds</h3>
      <div class="grid2">
        <label class="field">Display time zone<input type="text" data-key="display_timezone" value="${escapeHtml(s.display_timezone)}" placeholder="America/New_York"></label>
        <label class="field">Feed counts as stale after (seconds)<input type="number" min="2" max="120" data-key="stale_seconds" data-num value="${s.stale_seconds}"></label>
        ${toggle("Alert sounds", "alert_sounds")}
      </div>
      <p class="muted">The engine stores every time in UTC. This only changes what you see.</p>
    </div>
    <div class="section"><h3>Phone and remote access</h3>
      ${local ? `
      <div class="stack">
        <div class="muted">Password: ${auth.password_set ? "set" : "not set"} · Two-factor: ${auth.two_factor_set ? "on" : "off"} · Remote access: ${auth.remote_enabled ? `on (port ${auth.remote_port})` : "off"}</div>
        <div class="row"><input type="password" id="pw" placeholder="New password (12+ characters)"><button class="btn small" id="pw-save">Set password</button></div>
        <div class="row"><button class="btn small" id="tf-start">${auth.two_factor_set ? "Replace two-factor" : "Set up two-factor"}</button></div>
        <div id="tf-box"></div>
        <div class="row"><button class="btn small" id="remote">${auth.remote_enabled ? "Turn remote access off" : "Turn remote access on"}</button></div>
        <p class="muted">Remote access needs a password and two-factor. It is off by default. See NEEDS_NATHAN.md for how to reach it safely from your phone.</p>
      </div>` : `<p class="muted">Security settings can only be changed on the computer running the engine.</p>`}
    </div>
    <div class="section"><h3>Jarvis</h3>
      ${local ? `
      <div class="stack">
        <div class="muted">Jarvis: ${jarvis.key_set ? (jarvis.enabled ? "on" : "off") : "no key yet"} · Orders today: ${jarvis.orders_today ?? 0} of ${jarvis.max_orders_per_day ?? 20} · Owner PIN: ${jarvis.pin_set ? "set" : "not set"}</div>
        <div class="row"><button class="btn small" id="jv-key">${jarvis.key_set ? "Make a new Jarvis key" : "Create Jarvis key"}</button>
          ${jarvis.key_set ? `<button class="btn small" id="jv-toggle">${jarvis.enabled ? "Switch Jarvis off" : "Switch Jarvis on"}</button>` : ""}</div>
        <div id="jv-box"></div>
        <div class="grid2">
          <label class="field">Most contracts per Jarvis order<input type="number" min="0.001" step="any" id="jv-qty" value="${jarvis.max_quantity ?? 1}"></label>
          <label class="field">Most Jarvis orders per day<input type="number" min="0" max="500" id="jv-day" value="${jarvis.max_orders_per_day ?? 20}"></label>
        </div>
        <div class="muted">Paper accounts Jarvis may trade (none ticked = all paper accounts):</div>
        ${paperAccounts.map((a) => `<label class="field row"><input type="checkbox" data-jv-account="${a.id}" ${allowed.has(a.id) ? "checked" : ""}> ${escapeHtml(a.name)}</label>`).join("")}
        <div class="row"><button class="btn small" id="jv-save">Save Jarvis limits</button></div>
        <div class="row"><input type="password" inputmode="numeric" id="pin" placeholder="New owner PIN (4-12 digits)"><button class="btn small" id="pin-save">${jarvis.pin_set ? "Change PIN" : "Set PIN"}</button></div>
        <p class="muted">Jarvis can only trade paper accounts, and every Jarvis order still goes through the risk guard. Set an owner PIN so only you can switch accounts to live, resume after the kill switch or change these limits.</p>
      </div>` : `<p class="muted">Jarvis settings can only be changed on the computer running the engine.</p>`}
    </div>
    <div class="section"><h3>Backups</h3>
      <div class="row spread"><span class="muted">${backups.length} saved (one a day, last 30 kept)</span><button class="btn small" id="backup">Back up now</button></div>
    </div>
    <div class="section"><h3>About</h3><div class="muted">Trading App version ${escapeHtml(store.version)}. Charts by TradingView Lightweight Charts™ (Apache 2.0).</div></div>`;

  el.querySelectorAll("[data-theme]").forEach((card) => card.addEventListener("click", async () => { await saveSetting("theme", card.dataset.theme); renderSettings(el); }));
  el.querySelectorAll("[data-key]").forEach((input) => {
    const key = input.dataset.key;
    input.addEventListener("change", () => {
      let value = input.type === "checkbox" ? input.checked : input.value;
      if (input.dataset.num !== undefined) value = Number(value);
      saveSetting(key, value);
    });
  });
  el.querySelectorAll("[data-clear]").forEach((b) => b.addEventListener("click", async () => { await saveSetting(b.dataset.clear, ""); renderSettings(el); }));
  const click = (id, fn) => el.querySelector(id)?.addEventListener("click", async () => {
    try { await fn(); } catch (problem) { toast(problem.message, "blocked"); }
  });
  click("#pw-save", async () => { await post("/api/auth/password", { password: el.querySelector("#pw").value }); toast("Password set"); renderSettings(el); });
  click("#tf-start", async () => {
    const { secret, uri } = await post("/api/auth/two-factor/start");
    const box = el.querySelector("#tf-box");
    box.innerHTML = `<div class="message">Add this to your authenticator app (Google Authenticator, Authy, 1Password…).<br>
      Key: <code class="num">${escapeHtml(secret)}</code><br><small class="muted">${escapeHtml(uri)}</small></div>
      <div class="row"><input id="tf-code" inputmode="numeric" placeholder="6-digit code"><button class="btn small" id="tf-ok">Confirm</button></div>`;
    box.querySelector("#tf-ok").addEventListener("click", async () => {
      try { await post("/api/auth/two-factor/confirm", { code: box.querySelector("#tf-code").value }); toast("Two-factor is on"); renderSettings(el); }
      catch (problem) { toast(problem.message, "blocked"); }
    });
  });
  click("#remote", async () => { const r = await post("/api/auth/remote", { enabled: !auth.remote_enabled }); toast(r.note); renderSettings(el); });
  click("#jv-key", async () => {
    const { key, note } = await post("/api/owner/jarvis/key");
    el.querySelector("#jv-box").innerHTML = `<div class="message">${escapeHtml(note)}<br><code class="num">${escapeHtml(key)}</code></div>`;
  });
  click("#jv-toggle", async () => { await put("/api/owner/jarvis", { enabled: !jarvis.enabled }); renderSettings(el); });
  click("#jv-save", async () => {
    const ids = [...el.querySelectorAll("[data-jv-account]")].filter((c) => c.checked).map((c) => c.dataset.jvAccount);
    await put("/api/owner/jarvis", { max_quantity: Number(el.querySelector("#jv-qty").value), max_orders_per_day: Number(el.querySelector("#jv-day").value), allowed_account_ids: ids });
    toast("Jarvis limits saved"); renderSettings(el);
  });
  click("#pin-save", async () => { await post("/api/owner/pin", { pin: el.querySelector("#pin").value }); toast("Owner PIN saved"); renderSettings(el); });
  click("#backup", async () => { await post("/api/backups"); toast("Backup saved"); renderSettings(el); });
}

function toggle(label, key) {
  return `<label class="field row"><input type="checkbox" data-key="${key}" ${store.settings[key] ? "checked" : ""}> ${label}</label>`;
}

function colorField(label, key) {
  const value = store.settings[key];
  return `<label class="field">${label}<span class="row"><input type="color" data-key="${key}" value="${value || "#888888"}">
    <button class="btn small" type="button" data-clear="${key}">${value ? "Use theme's" : "theme's own"}</button></span></label>`;
}
