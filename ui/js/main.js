// The main screen: puts the grid, watchlist, side dock, top strip, banners and
// kill switch together, and feeds them live updates from the engine.

import { connectLive, get, isConnected, on, post, put } from "./api.js";
import { activeAccount, loadState, onChange, refreshAccounts, refreshScripts, setActiveAccount, store } from "./store.js";
import { applyTheme } from "./themes.js";
import { escapeHtml, money, percent } from "./format.js";
import { Grid, LAYOUTS, LAYOUT_LABELS } from "./grid.js";
import { Watchlist } from "./watchlist.js";
import { beep, toast } from "./ui.js";
import { renderTrade, paintTables } from "./panels/trade.js";
import { renderScripts } from "./panels/scripts.js";
import { renderBacktest } from "./panels/backtest.js";
import { renderAccounts } from "./panels/accounts.js";
import { renderLog } from "./panels/log.js";
import { renderSettings, saveSetting } from "./panels/settings.js";

const $ = (id) => document.getElementById(id);

const TABS = [
  { key: "trade", label: "Trade", render: (el) => renderTrade(el, ctx) },
  { key: "scripts", label: "Scripts", desktopOnly: true, render: (el) => renderScripts(el, ctx) },
  { key: "backtest", label: "Backtest", desktopOnly: true, render: (el) => renderBacktest(el, ctx, backtestScript) },
  { key: "accounts", label: "Accounts", render: (el) => renderAccounts(el, ctx) },
  { key: "log", label: "Log", render: (el) => renderLog(el) },
  { key: "settings", label: "Settings", render: (el) => renderSettings(el) },
];

let grid;
let watchlist;
let currentTab = "trade";
let backtestScript = null;
let workspaceName = "Default";
let saveTimer = null;
let banners = { engineDown: false };

// What the panels are allowed to ask the main screen for.
const ctx = {
  activePane: () => grid.activePane(),
  activeSymbol: () => grid.activePane()?.config.symbol,
  rerenderDock: () => showTab(currentTab),
  openBacktest: (scriptId) => { backtestScript = scriptId; showTab("backtest"); },
  onPrice: null,
};

// ---- Start up ------------------------------------------------------------------------

async function start() {
  try {
    await loadState();
  } catch (problem) {
    document.body.innerHTML = `<div class="banner danger">The engine isn't answering: ${escapeHtml(problem.message)}. Start it with start_app.bat.</div>`;
    return;
  }
  applyTheme(store.settings);

  grid = new Grid($("grid"), scheduleSave);
  grid.onActiveChange = () => { watchlist?.renderItems(); if (currentTab === "trade") showTab("trade"); renderBanners(); };
  watchlist = new Watchlist($("watchlist"), {
    onPick: (symbol) => grid.activePane().setSymbol(symbol),
    onChange: scheduleSave,
    onSide: () => saveSetting("watchlist_side", store.settings.watchlist_side === "left" ? "right" : "left").then(placeWatchlist),
    activeSymbol: () => ctx.activeSymbol(),
  });
  placeWatchlist();
  buildLayoutButtons();
  buildTabs();
  wireDropOnCharts();
  wirePhoneNav();

  await loadWorkspaceList();
  const saved = store.workspaces.includes(workspaceName) ? await get(`/api/workspaces/${encodeURIComponent(workspaceName)}`).catch(() => null) : null;
  restoreWorkspace(saved);

  $("kill-switch").addEventListener("click", killSwitch);
  wireLive();
  connectLive();
  renderStrip();
  renderBanners();
  setInterval(pollAccounts, 2000);
  setInterval(renderBanners, 1000);
  watchFrameRate();
}

// ---- Workspaces (saved layouts) -----------------------------------------------------------

async function loadWorkspaceList() {
  const select = $("workspace-select");
  const names = Array.from(new Set(["Default", ...store.workspaces]));
  select.innerHTML = names.map((n) => `<option ${n === workspaceName ? "selected" : ""}>${escapeHtml(n)}</option>`).join("");
  select.onchange = async () => {
    await saveNow();
    workspaceName = select.value;
    restoreWorkspace(await get(`/api/workspaces/${encodeURIComponent(workspaceName)}`).catch(() => null));
  };
  $("workspace-save-as").onclick = async () => {
    const name = prompt("Name for this layout:");
    if (!name) return;
    workspaceName = name.trim();
    await saveNow();
    store.workspaces = Array.from(new Set([...store.workspaces, workspaceName]));
    loadWorkspaceList();
    toast(`Saved layout "${workspaceName}"`);
  };
}

function restoreWorkspace(saved) {
  if (saved?.grid) {
    grid.active = saved.grid.active || 0;
    grid.setLayout(saved.grid.layout, saved.grid.charts, { cols: saved.grid.cols, rows: saved.grid.rows });
  } else {
    grid.setLayout(window.innerWidth < 760 ? "1" : "2v");
  }
  if (saved?.watchlist) watchlist.restore(saved.watchlist);
  const tab = TABS.find((t) => t.key === saved?.tab);
  if (tab && !(tab.desktopOnly && window.innerWidth < 760)) currentTab = tab.key;
  showTab(currentTab);
  markLayoutButton();
}

function scheduleSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveNow, 800);    // the layout saves itself; nothing to remember
  markLayoutButton();
}

async function saveNow() {
  clearTimeout(saveTimer);
  if (!grid) return;
  try {
    await put(`/api/workspaces/${encodeURIComponent(workspaceName)}`, { grid: grid.state(), watchlist: watchlist.state(), tab: currentTab });
  } catch (problem) { console.warn("Layout not saved:", problem.message); }
}

function buildLayoutButtons() {
  const box = $("layout-buttons");
  box.innerHTML = Object.keys(LAYOUTS).map((name) => `<button class="btn icon small" data-layout="${name}" title="${LAYOUTS[name].cells.length} chart(s)">${LAYOUT_LABELS[name]}</button>`).join("");
  box.querySelectorAll("[data-layout]").forEach((b) => b.addEventListener("click", () => grid.setLayout(b.dataset.layout)));
}

function markLayoutButton() {
  document.querySelectorAll("[data-layout]").forEach((b) => b.classList.toggle("active", b.dataset.layout === grid.layout));
}

function placeWatchlist() {
  const right = store.settings.watchlist_side === "right";
  const ws = $("workspace");
  ws.classList.toggle("watch-right", right);
  const list = $("watchlist");
  // Order: [watchlist] [charts] [dock] on the left setting; [dock] [charts] [watchlist] on the right.
  if (right) { ws.prepend($("dock")); ws.append(list); } else { ws.prepend(list); ws.append($("dock")); }
}

// Drag a symbol from the watchlist onto any chart to show it there.
function wireDropOnCharts() {
  const el = $("grid");
  el.addEventListener("dragover", (e) => { if (e.dataTransfer.types.includes("text/symbol")) e.preventDefault(); });
  el.addEventListener("drop", (e) => {
    const symbol = e.dataTransfer.getData("text/symbol");
    const paneEl = e.target.closest(".pane");
    const pane = grid.panes.find((p) => p.el === paneEl);
    if (symbol && pane) { e.preventDefault(); grid.activate(grid.panes.indexOf(pane)); pane.setSymbol(symbol); }
  });
}

// ---- Side dock -----------------------------------------------------------------------------

function buildTabs() {
  const nav = $("dock-tabs");
  nav.innerHTML = TABS.map((t) => `<button class="btn small ${t.desktopOnly ? "desktop-only" : ""}" data-tab="${t.key}"><span class="tab-label">${t.label}</span></button>`).join("");
  nav.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => { showTab(b.dataset.tab); scheduleSave(); }));
}

let tabRenderId = 0;
async function showTab(key) {
  currentTab = key;
  ctx.onPrice = null;
  document.querySelectorAll("#dock-tabs [data-tab]").forEach((b) => b.classList.toggle("active", b.dataset.tab === key));
  const body = $("dock-body");
  const id = ++tabRenderId;
  try {
    await TABS.find((t) => t.key === key).render(body);
  } catch (problem) {
    if (id === tabRenderId) body.innerHTML = `<div class="message blocked">This panel couldn't load: ${escapeHtml(problem.message)}</div>`;
  }
}

// ---- Top strip, kill switch and banners -----------------------------------------------------

function renderStrip() {
  const account = activeAccount();
  const n = account?.numbers || {};
  const used = n.used || 0;
  const today = n.day_start_balance ? n.equity - n.day_start_balance : null;
  $("strip").innerHTML = `
    <select id="account-select" title="Active account">${store.accounts.map((a) => `<option value="${a.id}" ${a.id === account?.id ? "selected" : ""}>${escapeHtml(a.name)}</option>`).join("")}</select>
    ${account ? `<span class="badge ${account.mode === "LIVE" ? "live" : "paper"}">${account.mode}</span>
    <div class="stat"><span class="label">Balance</span><span class="value">${money(n.balance)}</span></div>
    <div class="stat"><span class="label">Open P&amp;L</span><span class="value ${n.open_pnl > 0 ? "up" : n.open_pnl < 0 ? "down" : ""}">${money(n.open_pnl)}</span></div>
    <div class="stat"><span class="label">Today</span><span class="value ${today > 0 ? "up" : today < 0 ? "down" : ""}">${today === null ? "–" : money(today)}</span></div>
    ${n.room_left !== undefined ? `<div class="stat"><span class="label">Room left</span><span class="value">${money(n.room_left)}</span></div>` : ""}
    <div class="stat" title="How much of the allowed loss is used"><span class="label">Loss used ${percent(used)}</span><div class="meter ${used >= 1 ? "danger" : used >= 0.7 ? "warn" : ""}"><div style="width:${Math.min(100, used * 100)}%"></div></div></div>` : ""}`;
  $("account-select").addEventListener("change", (e) => setActiveAccount(e.target.value));
}

async function killSwitch() {
  const button = $("kill-switch");
  button.disabled = true;
  button.textContent = "STOPPING…";
  try {
    const report = await post("/api/kill-switch");
    toast(report.ok ? "Everything stopped, cancelled and closed. Trading is halted." : "Kill switch ran, but something didn't confirm. Check your broker NOW.", report.ok ? "ok" : "blocked",
      (report.steps || []).map((s) => s.text || s).join("\n"));
    store.tradingHalted = true;
  } catch (problem) {
    toast(`Kill switch couldn't reach the engine: ${problem.message}. Close positions at your broker.`, "blocked");
  }
  button.disabled = false;
  button.textContent = "KILL SWITCH";
  await refreshAccounts();
  refreshScripts();
}

function renderBanners() {
  if (!grid) return;
  const items = [];
  if (banners.engineDown) items.push(["danger", "Lost connection to the engine. Prices and orders on screen may be out of date. Reconnecting…"]);
  if (store.tradingHalted) items.push(["danger", "Trading is halted (kill switch or safety stop). No new orders can be sent.", "Resume trading", async () => { await post("/api/trading/resume"); store.tradingHalted = false; renderBanners(); }]);
  const account = activeAccount();
  const n = account?.numbers || {};
  if (n.balance_mismatch) items.push(["danger", `${account.name}: the app's balance and the broker's disagree. New orders are blocked until you check.`, "Open account", () => showTab("accounts")]);
  if (n.halted && !store.tradingHalted) items.push(["danger", `${account.name} is halted: ${n.halt_reason || "loss limit reached"}.`, "Open account", () => showTab("accounts")]);
  else if ((n.used || 0) >= 0.7) items.push(["warn", `${account.name} has used ${percent(n.used)} of its allowed loss.`]);
  if (account?.mode === "LIVE") items.push(["danger", `LIVE account: ${account.name}. Orders use real money.`]);
  const symbol = ctx.activeSymbol();
  const feed = store.feeds[symbol];
  if (feed === "stale") items.push(["warn", `${symbol}: prices haven't updated recently (feed is stale). The chart may be out of date.`]);
  if (feed === "down") items.push(["danger", `${symbol}: the price feed is down. Orders on this symbol are blocked.`]);
  const box = $("banners");
  const signature = JSON.stringify(items.map((i) => i.slice(0, 3)));
  if (box.dataset.sig === signature) return;
  box.dataset.sig = signature;
  box.innerHTML = "";
  for (const [kind, text, buttonText, action] of items) {
    const div = document.createElement("div");
    div.className = `banner ${kind}`;
    div.innerHTML = `<span>${escapeHtml(text)}</span>`;
    if (buttonText) {
      const b = document.createElement("button");
      b.className = "btn small";
      b.textContent = buttonText;
      b.addEventListener("click", async () => { try { await action(); } catch (p) { toast(p.message, "blocked"); } });
      div.appendChild(b);
    }
    box.appendChild(div);
  }
}

// ---- Live updates ---------------------------------------------------------------------------

let accountsTimer = null;
function accountsSoon() {
  clearTimeout(accountsTimer);
  accountsTimer = setTimeout(() => refreshAccounts().catch(() => {}), 250);
}

async function pollAccounts() {
  // The engine also pushes changes; this catches anything a push missed.
  if (isConnected()) await refreshAccounts().catch(() => {});
}

function wireLive() {
  on("connection", (up) => {
    banners.engineDown = !up;
    renderBanners();
    if (up) loadState().then(() => grid.forEach((p) => p.load())).catch(() => {});
  });
  on("tick", (t) => {
    store.prices[t.symbol] = t.price;
    watchlist.onTick(t);
    if (t.symbol === ctx.activeSymbol()) ctx.onPrice?.();
  });
  on("feed", (f) => { store.feeds[f.symbol] = f.status; renderBanners(); });
  on("account", accountsSoon);
  on("guard", () => { accountsSoon(); if (currentTab === "log") showTab("log"); });
  on("trading", (t) => { store.tradingHalted = t.halted; renderBanners(); });
  on("run", () => refreshScripts().then(() => { if (currentTab === "scripts") showTab("scripts"); }));
  on("alert", (a) => {
    toast(a.message, a.level === "danger" ? "blocked" : a.level === "warning" ? "warn" : "ok");
    if (store.settings.alert_sounds) beep(a.level);
  });
  on("settings", (s) => { store.settings[s.key] = s.value; applyTheme(store.settings); grid.forEach((p) => p.applyStyle()); });

  onChange((what) => {
    renderStrip();
    renderBanners();
    if (what === "account" || what === "accounts" || what === "all") {
      grid.forEach((p) => p.refreshTrading());
      if (currentTab === "trade") {
        const body = $("dock-body");
        if (what === "accounts" && body.querySelector("#positions")) paintTables(body, activeAccount());
        else showTab("trade");
      } else if (currentTab === "accounts" && what !== "accounts") showTab("accounts");
    }
    if (what === "settings") { grid.forEach((p) => p.applyStyle()); placeWatchlist(); }
  });
}

// ---- Smoothness: drop animated effects if the screen can't keep 50 frames a second -----------

function watchFrameRate() {
  let frames = 0;
  let since = performance.now();
  let slowSeconds = 0;
  const tick = (now) => {
    frames++;
    if (now - since >= 1000) {
      const fps = (frames * 1000) / (now - since);
      frames = 0;
      since = now;
      slowSeconds = fps < 50 && !document.hidden ? slowSeconds + 1 : 0;
      if (slowSeconds >= 3 && !window.__effectsPaused && store.settings.effects_enabled) {
        window.__effectsPaused = true;
        document.body.classList.add("effects-paused");
        grid.forEach((p) => p.applyStyle());
        toast("Animated effects paused to keep charts smooth. You can lower effects in Settings.", "warn");
      }
    }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

// ---- Phone ----------------------------------------------------------------------------------

function wirePhoneNav() {
  document.querySelectorAll("[data-phone]").forEach((b) => b.addEventListener("click", () => {
    const what = b.dataset.phone;
    const list = $("watchlist");
    if (what === "watchlist") { list.classList.toggle("phone-open"); return; }
    list.classList.remove("phone-open");
    showTab(what);
    $("dock").scrollIntoView({ behavior: "smooth" });
  }));
  $("watchlist").addEventListener("click", (e) => { if (e.target.closest(".wl-item") && window.innerWidth < 760) $("watchlist").classList.remove("phone-open"); });
}

window.addEventListener("beforeunload", () => saveNow());
start();
