// The watchlist sidebar: tabs by market plus the owner's own lists, live prices
// and daily change, search, collapse, resize and switch sides (bible 6A).

import { get } from "./api.js";
import { store, market } from "./store.js";
import { escapeHtml, price as fmtPrice } from "./format.js";

const CUSTOM_KEY = "customWatchlists";

export class Watchlist {
  constructor(el, hooks) {
    this.el = el;
    this.hooks = hooks;               // onPick(symbol), onChange()
    this.tab = "Crypto";
    this.collapsed = false;
    this.custom = loadCustom();
    this.quotes = {};
    this.render();
    setInterval(() => this.refreshQuotes(), 3000);
  }

  lists() { return { ...store.watchlists, ...this.custom }; }

  render() {
    const lists = this.lists();
    if (!lists[this.tab]) this.tab = Object.keys(lists)[0];
    this.el.classList.toggle("collapsed", this.collapsed);
    this.el.innerHTML = `
      <div class="wl-head">
        <button class="btn icon small" data-act="collapse" title="Collapse or expand">${this.collapsed ? "»" : "«"}</button>
        <strong class="wl-title">${this.collapsed ? "" : "Watchlist"}</strong>
        <span style="flex:1"></span>
        ${this.collapsed ? "" : `<button class="btn icon small" data-act="side" title="Move to the other side">⇄</button>
        <button class="btn icon small" data-act="newlist" title="New list">+</button>`}
      </div>
      <div class="wl-search"><input type="text" placeholder="Search symbols…" /><div class="wl-results hidden"></div></div>
      <div class="wl-tabs">${Object.keys(lists).map((name) => `<button class="btn small ${name === this.tab ? "active" : ""}" data-tab="${escapeHtml(name)}">${escapeHtml(name)}</button>`).join("")}</div>
      <div class="wl-body"></div>`;
    this.el.querySelector("[data-act=collapse]").addEventListener("click", () => { this.collapsed = !this.collapsed; this.render(); this.hooks.onChange(); });
    this.el.querySelector("[data-act=side]")?.addEventListener("click", () => this.hooks.onSide());
    this.el.querySelector("[data-act=newlist]")?.addEventListener("click", () => {
      const name = prompt("Name for the new list:");
      if (name && !lists[name]) { this.custom[name] = []; saveCustom(this.custom); this.tab = name; this.render(); }
    });
    this.el.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => { this.tab = b.dataset.tab; this.render(); this.hooks.onChange(); }));
    const input = this.el.querySelector(".wl-search input");
    const results = this.el.querySelector(".wl-results");
    input.addEventListener("input", () => {
      const q = input.value.trim().toLowerCase();
      if (!q) { results.classList.add("hidden"); return; }
      const found = Object.values(store.markets).filter((m) => m.symbol.toLowerCase().includes(q) || m.name.toLowerCase().includes(q)).slice(0, 20);
      results.innerHTML = found.map((m) => `<div data-sym="${m.symbol}"><strong>${escapeHtml(m.symbol)}</strong> <span class="muted">${escapeHtml(m.name)}</span></div>`).join("") || `<div class="muted">No match</div>`;
      results.classList.remove("hidden");
      results.querySelectorAll("[data-sym]").forEach((row) => row.addEventListener("click", () => {
        this.hooks.onPick(row.dataset.sym);
        if (this.custom[this.tab] && !this.custom[this.tab].includes(row.dataset.sym)) {
          this.custom[this.tab].push(row.dataset.sym);
          saveCustom(this.custom);
        }
        input.value = "";
        results.classList.add("hidden");
        this.renderItems();
      }));
    });
    this.renderItems();
  }

  renderItems() {
    const body = this.el.querySelector(".wl-body");
    if (!body) return;
    const symbols = this.lists()[this.tab] || [];
    const selected = this.hooks.activeSymbol();
    body.innerHTML = symbols.map((s) => {
      const m = market(s);
      return `<div class="wl-item ${s === selected ? "selected" : ""}" data-sym="${s}" draggable="true">
        <span class="sym">${escapeHtml(s.split(":")[1])}</span><span class="num price" data-price="${s}">–</span>
        <span class="name">${escapeHtml(m?.name || s)}</span><span class="num chg" data-chg="${s}"></span>
      </div>`;
    }).join("") || `<div class="muted" style="padding:10px">Empty list. Search above to add symbols.</div>`;
    body.querySelectorAll(".wl-item").forEach((row) => {
      row.addEventListener("click", () => { this.hooks.onPick(row.dataset.sym); this.renderItems(); });
      row.addEventListener("dragstart", (e) => e.dataTransfer.setData("text/symbol", row.dataset.sym));
      row.addEventListener("contextmenu", (e) => {
        if (!this.custom[this.tab]) return;
        e.preventDefault();
        if (confirm(`Remove ${row.dataset.sym} from ${this.tab}?`)) {
          this.custom[this.tab] = this.custom[this.tab].filter((s) => s !== row.dataset.sym);
          saveCustom(this.custom);
          this.renderItems();
        }
      });
    });
    this.paintQuotes();
    this.refreshQuotes();
  }

  async refreshQuotes() {
    if (this.collapsed) return;
    const symbols = this.lists()[this.tab] || [];
    if (!symbols.length) return;
    try {
      Object.assign(this.quotes, await get(`/api/quotes?symbols=${encodeURIComponent(symbols.join(","))}`));
    } catch (e) { return; }
    this.paintQuotes();
  }

  onTick(tick) {
    const q = this.quotes[tick.symbol];
    if (q) q.price = tick.price;
    const cell = this.el.querySelector(`[data-price="${CSS.escape(tick.symbol)}"]`);
    if (cell) cell.textContent = fmtPrice(tick.price, tick.symbol);
  }

  paintQuotes() {
    for (const [symbol, q] of Object.entries(this.quotes)) {
      const p = this.el.querySelector(`[data-price="${CSS.escape(symbol)}"]`);
      const c = this.el.querySelector(`[data-chg="${CSS.escape(symbol)}"]`);
      if (p) p.textContent = fmtPrice(q.price, symbol);
      if (c) {
        c.textContent = q.change_percent === null || q.change_percent === undefined ? (q.feed === "down" ? "offline" : "") : `${q.change_percent > 0 ? "+" : ""}${q.change_percent.toFixed(2)}%`;
        c.className = `num chg ${q.change_percent > 0 ? "up" : q.change_percent < 0 ? "down" : "muted"}`;
      }
    }
  }

  state() { return { tab: this.tab, collapsed: this.collapsed, custom: this.custom }; }
  restore(s) {
    if (!s) return;
    this.tab = s.tab || this.tab;
    this.collapsed = !!s.collapsed;
    if (s.custom) { this.custom = { ...s.custom, ...this.custom }; saveCustom(this.custom); }
    this.render();
  }
}

function loadCustom() {
  try { return JSON.parse(localStorage.getItem(CUSTOM_KEY) || "{}"); } catch (e) { return {}; }
}
function saveCustom(lists) {
  try { localStorage.setItem(CUSTOM_KEY, JSON.stringify(lists)); } catch (e) { /* private window */ }
}
