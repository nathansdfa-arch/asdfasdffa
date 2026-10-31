// The chart grid: one view box split into 1, 2, 3, 4 or 6 charts with resizable
// dividers. Clicking a chart makes it active (glowing border). Double-click
// expands it; double-click again or Escape returns to the grid (bible 6A).

import { ChartPane } from "./chart.js";

export const LAYOUTS = {
  "1": { cols: [1], rows: [1], cells: [[0, 0, 1, 1]] },
  "2v": { cols: [1, 1], rows: [1], cells: [[0, 0, 1, 1], [1, 0, 1, 1]] },
  "2h": { cols: [1], rows: [1, 1], cells: [[0, 0, 1, 1], [0, 1, 1, 1]] },
  "3": { cols: [1.4, 1], rows: [1, 1], cells: [[0, 0, 1, 2], [1, 0, 1, 1], [1, 1, 1, 1]] },
  "4": { cols: [1, 1], rows: [1, 1], cells: [[0, 0, 1, 1], [1, 0, 1, 1], [0, 1, 1, 1], [1, 1, 1, 1]] },
  "6": { cols: [1, 1, 1], rows: [1, 1], cells: [[0, 0, 1, 1], [1, 0, 1, 1], [2, 0, 1, 1], [0, 1, 1, 1], [1, 1, 1, 1], [2, 1, 1, 1]] },
};
export const LAYOUT_LABELS = { "1": "▢", "2v": "◫", "2h": "⊟", "3": "◧", "4": "⊞", "6": "▦" };

const DEFAULT_SYMBOLS = ["DEMO:ES", "BYBIT:BTCUSDT", "DEMO:EURUSD", "DEMO:NQ", "BYBIT:ETHUSDT", "DEMO:XAUUSD"];

export class Grid {
  constructor(el, onChange) {
    this.el = el;
    this.onChange = onChange;
    this.panes = [];
    this.layout = "1";
    this.cols = [1];
    this.rows = [1];
    this.active = 0;
    this.maximized = null;
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && this.maximized !== null) this.toggleMax(this.panes[this.maximized]); });
  }

  activePane() { return this.panes[this.active] || this.panes[0]; }

  setLayout(name, charts = null, sizes = null) {
    const spec = LAYOUTS[name] || LAYOUTS["1"];
    const old = this.panes.map((p) => p.config);
    const configs = charts || old;
    while (this.panes.length > spec.cells.length) this.panes.pop().destroy();
    this.layout = name;
    this.cols = sizes?.cols || [...spec.cols];
    this.rows = sizes?.rows || [...spec.rows];
    for (let i = 0; i < spec.cells.length; i++) {
      const config = configs[i] || { symbol: DEFAULT_SYMBOLS[i % DEFAULT_SYMBOLS.length], timeframe: "5m" };
      if (!this.panes[i]) {
        const pane = new ChartPane(structuredClone(config), {
          onActivate: (p) => this.activate(this.panes.indexOf(p)),
          onMaximize: (p) => this.toggleMax(p),
          onChange: () => this.onChange(),
        });
        this.panes.push(pane);
        this.el.appendChild(pane.el);
        pane.load();
      } else if (charts && JSON.stringify(this.panes[i].config) !== JSON.stringify(config)) {
        this.panes[i].config = structuredClone(config);
        this.panes[i].load();
      }
    }
    this.maximized = null;
    this.el.classList.remove("maximized");
    this.active = Math.min(this.active, this.panes.length - 1);
    this.place();
    this.activate(this.active, true);
    this.onChange();
  }

  place() {
    const spec = LAYOUTS[this.layout];
    this.el.style.gridTemplateColumns = this.cols.map((c) => `${c}fr`).join(" ");
    this.el.style.gridTemplateRows = this.rows.map((r) => `${r}fr`).join(" ");
    spec.cells.forEach(([c, r, cs, rs], i) => { this.panes[i].el.style.gridArea = `${r + 1} / ${c + 1} / span ${rs} / span ${cs}`; });
    this.el.querySelectorAll(".gutter").forEach((g) => g.remove());
    const total = (list) => list.reduce((a, b) => a + b, 0);
    let acc = 0;
    for (let i = 0; i < this.cols.length - 1; i++) {
      acc += this.cols[i];
      this.addGutter("col", i, (acc / total(this.cols)) * 100);
    }
    acc = 0;
    for (let i = 0; i < this.rows.length - 1; i++) {
      acc += this.rows[i];
      this.addGutter("row", i, (acc / total(this.rows)) * 100);
    }
  }

  addGutter(kind, index, percent) {
    const g = document.createElement("div");
    g.className = `gutter ${kind}`;
    if (kind === "col") g.style.left = `${percent}%`; else g.style.top = `${percent}%`;
    g.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      const list = kind === "col" ? this.cols : this.rows;
      const rect = this.el.getBoundingClientRect();
      const size = kind === "col" ? rect.width : rect.height;
      const start = kind === "col" ? e.clientX : e.clientY;
      const pair = list[index] + list[index + 1];
      const sum = list.reduce((a, b) => a + b, 0);
      const before = list[index];
      const move = (ev) => {
        const delta = ((kind === "col" ? ev.clientX : ev.clientY) - start) / size * sum;
        list[index] = Math.max(0.15 * pair, Math.min(0.85 * pair, before + delta));
        list[index + 1] = pair - list[index];
        this.place();
      };
      const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); this.onChange(); };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    });
    this.el.appendChild(g);
  }

  activate(index, force = false) {
    if (index < 0 || (index === this.active && !force)) return;
    this.active = index;
    this.panes.forEach((p, i) => p.el.classList.toggle("active", i === index));
    this.onActiveChange?.(this.activePane());
    if (!force) this.onChange();
  }

  toggleMax(pane) {
    const index = this.panes.indexOf(pane);
    if (this.maximized === index) {
      this.maximized = null;
      this.el.classList.remove("maximized");
      pane.el.classList.remove("max");
    } else {
      this.panes.forEach((p) => p.el.classList.remove("max"));
      this.maximized = index;
      pane.el.classList.add("max");
      this.el.classList.add("maximized");
      this.activate(index);
    }
  }

  state() {
    return { layout: this.layout, cols: this.cols, rows: this.rows, active: this.active, charts: this.panes.map((p) => p.config) };
  }

  forEach(fn) { this.panes.forEach(fn); }
}
