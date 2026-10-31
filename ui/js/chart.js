// One chart in the grid. Every chart is independent: its own symbol, timeframe,
// chart type, indicators, drawings and settings (bible section 6A).

import { get, on, post, watch } from "./api.js";
import { activeAccount, market, store } from "./store.js";
import { chartColors } from "./themes.js";
import { chartTime, decimalsFor, escapeHtml, price as fmtPrice } from "./format.js";
import { Overlay } from "./overlay.js";
import { toast, showResult } from "./ui.js";

const LC = window.LightweightCharts;
export const TIMEFRAMES = { "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400 };
const DAYS_FOR = { "1m": 30, "5m": 60, "15m": 120, "1h": 365, "4h": 730, "1d": 1825 };

export class ChartPane {
  constructor(config, hooks) {
    this.config = { symbol: "DEMO:ES", timeframe: "5m", type: "candles", indicators: [], ...config };
    this.hooks = hooks;           // onActivate, onMaximize, onChange
    this.lastBars = [];
    this.indicatorSeries = [];
    this.tradeLines = [];
    this.markers = null;
    this.extraMarkers = [];
    this.unsubscribe = [];
    this.build();
  }

  get seconds() { return TIMEFRAMES[this.config.timeframe]; }

  // ---- Building -----------------------------------------------------------------

  build() {
    this.el = document.createElement("div");
    this.el.className = "pane";
    this.el.innerHTML = `
      <div class="pane-head">
        <span class="sym" title="Click a symbol in the watchlist to change it"></span>
        <select class="tf" title="Timeframe">${Object.keys(TIMEFRAMES).map((t) => `<option>${t}</option>`).join("")}</select>
        <select class="ctype" title="Chart type"><option value="candles">Candles</option><option value="hollow">Hollow</option><option value="bars">Bars</option><option value="line">Line</option></select>
        <button class="btn small add-ind" title="Add an indicator script">+ Indicator</button>
        <div class="chips"></div>
        <div class="tools">
          <button class="btn icon small" data-tool="trend" title="Trend line">╱</button>
          <button class="btn icon small" data-tool="hline" title="Horizontal line">—</button>
          <button class="btn icon small" data-tool="rect" title="Rectangle">▭</button>
          <button class="btn icon small" data-tool="fib" title="Fibonacci retracement">ƒ</button>
          <button class="btn icon small" data-tool="text" title="Text note">T</button>
          <button class="btn small buy quick-buy" title="Market buy with the order ticket's size and stop">B</button>
          <button class="btn small sell quick-sell" title="Market sell with the order ticket's size and stop">S</button>
          <span class="badge paper mode-badge">PAPER</span>
        </div>
      </div>
      <div class="pane-body"><div class="bg-anim"></div><div class="chart"></div><div class="pane-loading">Loading…</div></div>`;
    this.head = this.el.querySelector(".pane-head");
    this.body = this.el.querySelector(".pane-body");
    this.loading = this.el.querySelector(".pane-loading");

    this.el.addEventListener("pointerdown", () => this.hooks.onActivate(this), { capture: true });
    this.body.addEventListener("dblclick", (e) => { if (!this.overlay.mode) this.hooks.onMaximize(this); });
    this.head.querySelector(".tf").addEventListener("change", (e) => this.setTimeframe(e.target.value));
    this.head.querySelector(".ctype").addEventListener("change", (e) => { this.config.type = e.target.value; this.makeMainSeries(); this.setBars(this.lastBars); this.hooks.onChange(); });
    this.head.querySelector(".add-ind").addEventListener("click", (e) => this.pickIndicator(e));
    this.head.querySelectorAll("[data-tool]").forEach((b) => b.addEventListener("click", () => this.overlay.setMode(b.dataset.tool)));
    this.head.querySelector(".quick-buy").addEventListener("click", () => this.quickOrder("buy"));
    this.head.querySelector(".quick-sell").addEventListener("click", () => this.quickOrder("sell"));
    this.body.addEventListener("contextmenu", (e) => this.contextMenu(e));

    this.makeChart();
    this.overlay = new Overlay(this);
    this.unsubscribe.push(on("candle", (m) => this.onCandle(m)));
  }

  makeChart() {
    const colors = chartColors(store.settings);
    this.chart = LC.createChart(this.body.querySelector(".chart"), {
      autoSize: true,
      layout: { background: this.background(colors), textColor: colors.text, fontFamily: getComputedStyle(document.body).fontFamily, attributionLogo: true, panes: { separatorColor: colors.border } },
      grid: { vertLines: { color: colors.grid }, horzLines: { color: colors.grid } },
      rightPriceScale: { borderColor: colors.border },
      timeScale: { borderColor: colors.border, timeVisible: true, secondsVisible: false, rightOffset: 8, tickMarkFormatter: (t, kind) => chartTime(t, ["year", "month", "day", "time", "time"][kind]) },
      localization: { timeFormatter: (t) => chartTime(t, "time") + "  " + chartTime(t, "day") },
      crosshair: { mode: LC.CrosshairMode.Normal },
      kineticScroll: { mouse: false, touch: true },
    });
    this.makeMainSeries();
    const redraw = () => this.overlay?.redraw();
    this.chart.timeScale().subscribeVisibleLogicalRangeChange(redraw);
    this.chart.subscribeCrosshairMove(redraw);
  }

  background(colors) {
    const mode = store.settings.chart_background;
    if (mode === "animated" && store.settings.effects_enabled) return { type: LC.ColorType.Solid, color: "rgba(0,0,0,0)" };
    if (mode === "gradient" && store.settings.effects_enabled) {
      return { type: LC.ColorType.VerticalGradient, topColor: colors.background, bottomColor: mix(colors.background, colors.accent, 0.06) };
    }
    return { type: LC.ColorType.Solid, color: colors.background };
  }

  makeMainSeries() {
    if (this.series) this.chart.removeSeries(this.series);
    const colors = chartColors(store.settings);
    const symbol = this.config.symbol;
    const priceFormat = { type: "price", precision: decimalsFor(symbol), minMove: market(symbol)?.tick_size || 0.01 };
    const type = this.config.type;
    const hollow = type === "hollow" || store.settings.candle_hollow;
    if (type === "line") {
      this.series = this.chart.addSeries(LC.LineSeries, { color: colors.accent, lineWidth: 2, priceFormat });
    } else if (type === "bars") {
      this.series = this.chart.addSeries(LC.BarSeries, { upColor: colors.up, downColor: colors.down, priceFormat });
    } else {
      this.series = this.chart.addSeries(LC.CandlestickSeries, {
        upColor: hollow ? "rgba(0,0,0,0)" : colors.up, downColor: colors.down,
        borderUpColor: colors.up, borderDownColor: colors.down, wickUpColor: colors.up, wickDownColor: colors.down, priceFormat,
      });
    }
    this.markers = LC.createSeriesMarkers(this.series, []);
    this.tradeLines = [];
    this.body.querySelector(".chart").style.filter = store.settings.candle_glow && store.settings.effects_enabled ? `drop-shadow(0 0 ${2 + store.settings.effect_intensity / 25}px ${mix(colors.accent, "#000000", 0.2)})` : "";
  }

  applyStyle() {
    if (this.destroyed) return;
    const colors = chartColors(store.settings);
    this.chart.applyOptions({
      layout: { background: this.background(colors), textColor: colors.text },
      grid: { vertLines: { color: colors.grid }, horzLines: { color: colors.grid } },
      rightPriceScale: { borderColor: colors.border }, timeScale: { borderColor: colors.border },
    });
    this.body.querySelector(".bg-anim").classList.toggle("on", store.settings.chart_background === "animated" && !!store.settings.effects_enabled && !window.__effectsPaused);
    this.makeMainSeries();
    this.setBars(this.lastBars);
    this.refreshTrading();
    this.overlay.redraw();
  }

  // ---- Data ------------------------------------------------------------------

  async load() {
    const { symbol, timeframe } = this.config;
    this.head.querySelector(".sym").textContent = symbol;
    this.head.querySelector(".tf").value = timeframe;
    this.head.querySelector(".ctype").value = this.config.type;
    this.loading.textContent = "Loading…";
    this.loading.classList.remove("hidden");
    this.makeMainSeries();
    const started = performance.now();
    try {
      const data = await get(`/api/candles?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}&days=${DAYS_FOR[timeframe]}`);
      if (this.destroyed || symbol !== this.config.symbol || timeframe !== this.config.timeframe) return;   // changed meanwhile
      const c = data.candles;
      const bars = c.t.map((t, i) => ({ time: t, open: c.o[i], high: c.h[i], low: c.l[i], close: c.c[i] }));
      this.setBars(bars);
      this.overlay.gaps = data.gaps;
      this.chart.timeScale().fitContent();
      if (bars.length > 300) this.chart.timeScale().setVisibleLogicalRange({ from: bars.length - 250, to: bars.length + 8 });
      this.loading.classList.add("hidden");
      this.note(data.warning || (data.gaps.length ? `${data.gaps.length} gap(s) in the data are shaded` : ""), data.warning ? "warn" : "");
      this.loadMs = Math.round(performance.now() - started);
      this.el.dataset.loadMs = String(this.loadMs);
      if (!bars.length) { this.loading.textContent = data.warning || "No candles available."; this.loading.classList.remove("hidden"); }
    } catch (problem) {
      this.loading.textContent = `Couldn't load prices: ${problem.message}`;
    }
    if (this.destroyed) return;
    watch(symbol, timeframe);
    this.overlay.drawings = await get(`/api/drawings?symbol=${encodeURIComponent(symbol)}`).catch(() => []);
    if (this.destroyed) return;
    this.overlay.redraw();
    await this.runIndicators();
    if (!this.destroyed) this.refreshTrading();
  }

  setBars(bars) {
    this.lastBars = bars;
    if (!this.series) return;
    if (this.config.type === "line") this.series.setData(bars.map((b) => ({ time: b.time, value: b.close })));
    else this.series.setData(bars);
  }

  onCandle(message) {
    if (message.symbol !== this.config.symbol || message.timeframe !== this.config.timeframe || !this.series) return;
    const c = message.candle;
    const bar = { time: c.time, open: c.open, high: c.high, low: c.low, close: c.close };
    const last = this.lastBars[this.lastBars.length - 1];
    if (last && bar.time < last.time) return;
    if (last && bar.time === last.time) this.lastBars[this.lastBars.length - 1] = bar;
    else this.lastBars.push(bar);
    this.series.update(this.config.type === "line" ? { time: bar.time, value: bar.close } : bar);
    if (message.finished && this.config.indicators.length) {
      clearTimeout(this.indicatorTimer);
      this.indicatorTimer = setTimeout(() => this.runIndicators(), 400);
    }
    this.updatePositionTitle();
    this.overlay.redraw();
  }

  setSymbol(symbol) {
    if (symbol === this.config.symbol) return;
    this.config.symbol = symbol;
    this.extraMarkers = [];
    this.load();
    this.hooks.onChange();
  }

  setTimeframe(timeframe) {
    this.config.timeframe = timeframe;
    this.extraMarkers = [];
    this.load();
    this.hooks.onChange();
  }

  note(text, kind = "") {
    let el = this.body.querySelector(".pane-note");
    if (!text) { el?.remove(); return; }
    if (!el) { el = document.createElement("div"); el.className = "pane-note"; this.body.appendChild(el); }
    el.textContent = text;
    el.style.color = kind === "warn" ? "var(--safe-warn)" : "";
  }

  roundPrice(value) {
    const tick = market(this.config.symbol)?.tick_size || 0.01;
    return Number((Math.round(value / tick) * tick).toFixed(decimalsFor(this.config.symbol)));
  }

  formatPrice(value) { return fmtPrice(value, this.config.symbol); }

  // ---- Indicators -----------------------------------------------------------------

  pickIndicator(event) {
    const indicators = store.scripts.filter((s) => s.kind === "indicator");
    const items = indicators.map((s) => ({ label: s.name, action: () => this.addIndicator(s.id) }));
    if (!items.length) items.push({ label: "No indicator scripts yet. Write one in the Scripts tab.", action: () => {} });
    openMenu(event.clientX, event.clientY, items);
  }

  async addIndicator(scriptId, inputs = {}) {
    const started = performance.now();
    this.config.indicators.push({ script_id: scriptId, inputs });
    await this.runIndicators();
    this.hooks.onChange();
    return Math.round(performance.now() - started);
  }

  removeIndicator(index) {
    this.config.indicators.splice(index, 1);
    this.runIndicators();
    this.hooks.onChange();
  }

  async runIndicators() {
    const { symbol, timeframe } = this.config;
    const results = await Promise.all(this.config.indicators.map((ind) =>
      post("/api/indicator", { script_id: ind.script_id, symbol, timeframe, days: DAYS_FOR[timeframe], inputs: ind.inputs })
        .catch((problem) => ({ ok: false, error: { message: problem.message } }))));
    if (this.destroyed || symbol !== this.config.symbol || timeframe !== this.config.timeframe) return;
    for (const s of this.indicatorSeries) this.chart.removeSeries(s);
    this.indicatorSeries = [];
    while (this.chart.panes().length > 1) this.chart.removePane(this.chart.panes().length - 1);
    const paneIndex = { price: 0 };
    const chips = this.head.querySelector(".chips");
    chips.innerHTML = "";
    results.forEach((result, i) => {
      const script = store.scripts.find((s) => s.id === this.config.indicators[i].script_id);
      const chip = document.createElement("span");
      chip.className = "chip" + (result.ok ? "" : " error");
      chip.innerHTML = `${escapeHtml(script?.name || "Indicator")} <button title="Remove">✕</button>`;
      chip.title = result.ok ? "" : result.error.message;
      chip.querySelector("button").addEventListener("click", () => this.removeIndicator(i));
      chips.appendChild(chip);
      if (!result.ok) { toast(`${script?.name || "Indicator"}: ${result.error.message}`, "blocked"); return; }
      const firstByPane = {};
      for (const plot of result.plots) {
        if (!(plot.pane in paneIndex)) paneIndex[plot.pane] = Object.keys(paneIndex).length;
        const index = paneIndex[plot.pane];
        const color = plot.color || chartColors(store.settings).accent;
        const definition = plot.style === "histogram" ? LC.HistogramSeries : LC.LineSeries;
        const options = plot.style === "histogram" ? { color, priceLineVisible: false, lastValueVisible: false } :
          { color, lineWidth: plot.width || 2, priceLineVisible: false, lastValueVisible: true, title: plot.name, pointMarkersVisible: plot.style === "dots", lineVisible: plot.style !== "dots" };
        const series = this.chart.addSeries(definition, options, index);
        series.setData(result.times.map((t, k) => plot.values[k] === null ? { time: t } : { time: t, value: plot.values[k] }));
        this.indicatorSeries.push(series);
        firstByPane[plot.pane] = firstByPane[plot.pane] || series;
      }
      for (const line of result.lines) {
        const target = firstByPane[line.pane] || (line.pane === "price" ? this.series : null);
        target?.createPriceLine({ price: line.value, color: line.color || "#7a7f99", lineWidth: 1, lineStyle: LC.LineStyle.Dashed, axisLabelVisible: false, title: line.name || "" });
      }
    });
    const panes = this.chart.panes();
    if (panes.length > 1) {
      panes[0].setStretchFactor(3);
      for (let k = 1; k < panes.length; k++) panes[k].setStretchFactor(1);
    }
  }

  // ---- Trading on the chart ----------------------------------------------------------

  refreshTrading() {
    if (this.destroyed) return;
    const account = activeAccount();
    const badge = this.head.querySelector(".mode-badge");
    const live = account?.mode === "LIVE";
    badge.textContent = live ? "LIVE" : "PAPER";
    badge.className = `badge mode-badge ${live ? "live" : "paper"}`;
    for (const line of this.tradeLines) this.series.removePriceLine(line);
    this.tradeLines = [];
    this.overlay.dragLines = [];
    if (!account) return;
    const symbol = this.config.symbol;
    const colors = chartColors(store.settings);
    const position = (account.positions || []).find((p) => p.symbol === symbol);
    if (position) {
      this.positionLine = this.series.createPriceLine({ price: position.average_price, color: colors.accent, lineWidth: 2, lineStyle: LC.LineStyle.Solid, axisLabelVisible: true, title: "" });
      this.positionInfo = position;
      this.tradeLines.push(this.positionLine);
      this.updatePositionTitle();
    } else {
      this.positionLine = null;
    }
    for (const order of account.orders || []) {
      if (order.symbol !== symbol || order.price === null) continue;
      const kind = order.role === "stop_loss" ? "stop" : order.role === "take_profit" ? "target" : "order";
      const label = kind === "stop" ? "STOP" : kind === "target" ? "TARGET" : `${order.side.toUpperCase()} ${order.order_type.toUpperCase()} ${order.quantity}`;
      const color = kind === "stop" ? colors.down : kind === "target" ? colors.up : colors.accent;
      const line = this.series.createPriceLine({ price: order.price, color, lineWidth: 1, lineStyle: LC.LineStyle.Dashed, axisLabelVisible: true, title: `${label}  ⇕` });
      this.tradeLines.push(line);
      this.overlay.dragLines.push({ price: order.price, kind, id: order.id, line, account_id: account.id, symbol });
    }
    this.loadMarkers(account);
  }

  updatePositionTitle() {
    if (!this.positionLine || !this.positionInfo) return;
    const p = this.positionInfo;
    const last = this.lastBars[this.lastBars.length - 1]?.close;
    const pv = market(this.config.symbol)?.point_value || 1;
    const pnl = last !== undefined ? (last - p.average_price) * p.quantity * pv : 0;
    this.positionLine.applyOptions({ title: `${p.quantity > 0 ? "LONG" : "SHORT"} ${Math.abs(p.quantity)}  ${pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}` });
  }

  async loadMarkers(account) {
    const fills = await get(`/api/accounts/${account.id}/fills?limit=300`).catch(() => []);
    const colors = chartColors(store.settings);
    const from = this.lastBars[0]?.time || 0;
    const marks = fills.filter((f) => f.symbol === this.config.symbol && f.time >= from).map((f) => ({
      time: Math.floor(f.time / this.seconds) * this.seconds,
      position: f.side === "buy" ? "belowBar" : "aboveBar",
      color: f.side === "buy" ? colors.up : colors.down,
      shape: f.side === "buy" ? "arrowUp" : "arrowDown",
      text: `${f.role === "entry" ? "" : f.role.replace("_", " ") + " "}${f.side} ${f.quantity} @ ${this.formatPrice(f.price)}`,
    }));
    this.markers?.setMarkers([...marks, ...this.extraMarkers].sort((a, b) => a.time - b.time));
  }

  showBacktestTrades(trades) {
    const colors = chartColors(store.settings);
    const marks = [];
    for (const t of trades) {
      const long = t.side === "long";
      marks.push({ time: Math.floor(t.entry_time / this.seconds) * this.seconds, position: long ? "belowBar" : "aboveBar", color: colors.accent, shape: long ? "arrowUp" : "arrowDown", text: `test ${t.side}` });
      if (t.exit_time) marks.push({ time: Math.floor(t.exit_time / this.seconds) * this.seconds, position: long ? "aboveBar" : "belowBar", color: t.pnl >= 0 ? colors.up : colors.down, shape: "circle", text: `${t.pnl >= 0 ? "+" : ""}${t.pnl.toFixed(0)}` });
    }
    this.extraMarkers = marks;
    const account = activeAccount();
    if (account) this.loadMarkers(account); else this.markers?.setMarkers(marks.sort((a, b) => a.time - b.time));
  }

  async onLineDragged(line, newPrice) {
    let result;
    try {
      if (line.kind === "stop") result = await post("/api/positions/stop", { account_id: line.account_id, symbol: line.symbol, price: newPrice });
      else if (line.kind === "target") result = await post("/api/positions/target", { account_id: line.account_id, symbol: line.symbol, price: newPrice });
      else result = await post("/api/orders/move", { account_id: line.account_id, order_id: line.id, price: newPrice });
    } catch (problem) {
      result = { ok: false, message: problem.message };
    }
    showResult(result, `${line.kind === "order" ? "Order" : line.kind === "stop" ? "Stop" : "Target"} moved to ${this.formatPrice(newPrice)}`);
    window.dispatchEvent(new Event("trading-changed"));
    if (!result.ok) line.line.applyOptions({ price: line.price });
  }

  ticketDefaults() {
    return store.ticket || { quantity: market(this.config.symbol)?.min_quantity || 1, stopTicks: 20, targetTicks: 0 };
  }

  async placeAt(side, kind, price) {
    const account = activeAccount();
    if (!account) return toast("Choose an account first.", "blocked");
    const t = this.ticketDefaults();
    const tick = market(this.config.symbol)?.tick_size || 0.01;
    const sign = side === "buy" ? 1 : -1;
    const entry = price ?? this.lastBars[this.lastBars.length - 1]?.close;
    const body = {
      account_id: account.id, symbol: this.config.symbol, side, quantity: t.quantity, order_type: kind, source: "chart",
      price: kind === "market" ? null : price,
      stop_loss: t.stopTicks ? this.roundPrice(entry - sign * t.stopTicks * tick) : null,
      take_profit: t.targetTicks ? this.roundPrice(entry + sign * t.targetTicks * tick) : null,
    };
    const result = await post("/api/orders", body).catch((problem) => ({ ok: false, message: problem.message }));
    showResult(result, `${side === "buy" ? "Buy" : "Sell"} ${kind} ${t.quantity} ${this.config.symbol} sent`);
    window.dispatchEvent(new Event("trading-changed"));
  }

  quickOrder(side) { this.placeAt(side, "market", null); }

  contextMenu(event) {
    event.preventDefault();
    const rect = this.body.getBoundingClientRect();
    const x = event.clientX - rect.left, y = event.clientY - rect.top;
    const raw = this.series.coordinateToPrice(y);
    if (raw === null) return;
    const at = this.roundPrice(raw);
    const last = this.lastBars[this.lastBars.length - 1]?.close ?? at;
    const account = activeAccount();
    const position = (account?.positions || []).find((p) => p.symbol === this.config.symbol);
    const items = [];
    if (at < last) items.push({ label: `Buy limit at ${this.formatPrice(at)}`, action: () => this.placeAt("buy", "limit", at) }, { label: `Sell stop at ${this.formatPrice(at)}`, action: () => this.placeAt("sell", "stop", at) });
    else items.push({ label: `Sell limit at ${this.formatPrice(at)}`, action: () => this.placeAt("sell", "limit", at) }, { label: `Buy stop at ${this.formatPrice(at)}`, action: () => this.placeAt("buy", "stop", at) });
    if (position) {
      items.push({ sep: true });
      items.push({ label: `Set stop loss at ${this.formatPrice(at)}`, action: async () => { const r = await post("/api/positions/stop", { account_id: account.id, symbol: this.config.symbol, price: at }).catch((p) => ({ ok: false, message: p.message })); showResult(r, "Stop loss set"); window.dispatchEvent(new Event("trading-changed")); } });
      items.push({ label: `Set target at ${this.formatPrice(at)}`, action: async () => { const r = await post("/api/positions/target", { account_id: account.id, symbol: this.config.symbol, price: at }).catch((p) => ({ ok: false, message: p.message })); showResult(r, "Target set"); window.dispatchEvent(new Event("trading-changed")); } });
      items.push({ label: "Close position", action: async () => { const r = await post("/api/positions/close", { account_id: account.id, symbol: this.config.symbol }).catch((p) => ({ ok: false, message: p.message })); showResult(r, "Position closed"); window.dispatchEvent(new Event("trading-changed")); } });
    }
    const drawing = this.overlay.drawingNear(x, y);
    items.push({ sep: true });
    if (drawing) items.push({ label: "Delete this drawing", action: () => this.overlay.remove(drawing) });
    if (this.overlay.drawings.length) items.push({ label: "Clear all drawings on this symbol", action: () => this.overlay.clear() });
    items.push({ label: "Reset zoom", action: () => this.chart.timeScale().fitContent() });
    openMenu(event.clientX, event.clientY, items);
  }

  updateToolButtons() {
    this.head.querySelectorAll("[data-tool]").forEach((b) => b.classList.toggle("active", b.dataset.tool === this.overlay.mode));
  }

  destroy() {
    this.destroyed = true;        // late replies for a removed chart are ignored
    clearTimeout(this.indicatorTimer);
    for (const off of this.unsubscribe) off();
    this.chart.remove();
    this.el.remove();
  }
}

// ---- Small helpers ----------------------------------------------------------------

export function openMenu(x, y, items) {
  document.querySelectorAll(".context-menu").forEach((m) => m.remove());
  const menu = document.createElement("div");
  menu.className = "context-menu";
  for (const item of items) {
    const row = document.createElement("div");
    if (item.sep) { row.className = "sep"; menu.appendChild(row); continue; }
    row.textContent = item.label;
    row.addEventListener("click", () => { menu.remove(); item.action(); });
    menu.appendChild(row);
  }
  document.body.appendChild(menu);
  const box = menu.getBoundingClientRect();
  menu.style.left = `${Math.min(x, innerWidth - box.width - 8)}px`;
  menu.style.top = `${Math.min(y, innerHeight - box.height - 8)}px`;
  setTimeout(() => document.addEventListener("pointerdown", function close(e) {
    if (!menu.contains(e.target)) { menu.remove(); document.removeEventListener("pointerdown", close); }
  }), 0);
}

function mix(a, b, amount) {
  const pa = parseInt(a.slice(1), 16), pb = parseInt(b.slice(1), 16);
  const channel = (shift) => Math.round(((pa >> shift) & 255) * (1 - amount) + ((pb >> shift) & 255) * amount);
  return `#${[16, 8, 0].map((s) => channel(s).toString(16).padStart(2, "0")).join("")}`;
}
