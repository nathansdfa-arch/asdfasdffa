// The layer on top of each chart: drawings (trend lines, horizontal lines, boxes,
// Fibonacci, notes), gap markings, and dragging order / stop / target lines.

import { del, put } from "./api.js";

const FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
const HIT = 6;   // pixels: how close the mouse must be to grab a line

export class Overlay {
  constructor(pane) {
    this.pane = pane;
    this.canvas = document.createElement("canvas");
    this.canvas.className = "overlay";
    pane.body.appendChild(this.canvas);
    this.ctx = this.canvas.getContext("2d");
    this.drawings = [];
    this.gaps = [];
    this.mode = null;          // drawing tool in use
    this.pending = null;       // first point of a two-point drawing
    this.preview = null;
    this.dragLines = [];       // [{price, kind, id, line}] lines the owner can drag
    this.dragging = null;
    this.frameRequested = false;

    // Capture-phase listeners run before the chart's own, so we can take over the
    // mouse for drawing and dragging without the chart panning underneath.
    const body = pane.body;
    body.addEventListener("pointerdown", (e) => this.onDown(e), { capture: true });
    body.addEventListener("mousedown", (e) => { if (this.mode || this.dragging) { e.stopPropagation(); e.preventDefault(); } }, { capture: true });
    body.addEventListener("pointermove", (e) => this.onMove(e), { capture: true });
    window.addEventListener("pointerup", (e) => this.onUp(e));
    new ResizeObserver(() => this.redraw()).observe(body);
  }

  // ---- Coordinates ------------------------------------------------------------

  xy(event) {
    const rect = this.pane.body.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  }

  toPoint(x, y) {
    const price = this.pane.series.coordinateToPrice(y);
    return { time: this.xToTime(x), price: this.pane.roundPrice(price) };
  }

  xToTime(x) {
    const scale = this.pane.chart.timeScale();
    const t = scale.coordinateToTime(x);
    if (t !== null) return t;
    const logical = scale.coordinateToLogical(x);
    const data = this.pane.lastBars;
    if (logical === null || !data.length) return null;
    const last = data.length - 1;
    return data[last].time + Math.round(logical - last) * this.pane.seconds;
  }

  timeToX(time) {
    const scale = this.pane.chart.timeScale();
    const x = scale.timeToCoordinate(time);
    if (x !== null) return x;
    const data = this.pane.lastBars;
    if (!data.length) return null;
    const last = data.length - 1;
    const logical = time > data[last].time ? last + (time - data[last].time) / this.pane.seconds : (time - data[0].time) / this.pane.seconds;
    return scale.logicalToCoordinate(logical);
  }

  // ---- Mouse --------------------------------------------------------------------

  setMode(mode) {
    this.mode = this.mode === mode ? null : mode;
    this.pending = null;
    this.preview = null;
    this.pane.body.classList.toggle("drawing", !!this.mode);
    this.pane.updateToolButtons();
    this.redraw();
  }

  onDown(event) {
    if (event.button !== 0) return;
    const { x, y } = this.xy(event);
    if (this.mode) {
      event.stopPropagation();
      event.preventDefault();
      this.addPoint(this.toPoint(x, y));
      return;
    }
    const line = this.lineAt(y);
    if (line) {
      event.stopPropagation();
      event.preventDefault();
      this.dragging = { ...line, startY: y };
      this.pane.chart.applyOptions({ handleScroll: false, handleScale: false });
    }
  }

  onMove(event) {
    const { x, y } = this.xy(event);
    if (this.dragging) {
      const price = this.pane.roundPrice(this.pane.series.coordinateToPrice(y));
      this.dragging.newPrice = price;
      this.dragging.line.applyOptions({ price });
      event.stopPropagation();
      return;
    }
    if (this.mode && this.pending) {
      this.preview = this.toPoint(x, y);
      this.redraw();
    }
    this.pane.body.style.cursor = this.mode ? "crosshair" : (this.lineAt(y) ? "ns-resize" : "");
  }

  onUp() {
    if (!this.dragging) return;
    const drag = this.dragging;
    this.dragging = null;
    this.pane.chart.applyOptions({ handleScroll: true, handleScale: true });
    if (drag.newPrice !== undefined && drag.newPrice !== drag.price) this.pane.onLineDragged(drag, drag.newPrice);
  }

  lineAt(y) {
    return this.dragLines.find((l) => {
      const ly = this.pane.series.priceToCoordinate(l.price);
      return ly !== null && Math.abs(ly - y) <= HIT;
    });
  }

  // ---- Drawings -------------------------------------------------------------------

  addPoint(point) {
    if (point.time === null || point.price === null) return;
    const kind = this.mode;
    if (kind === "hline") return this.finish({ kind, points: [point] });
    if (kind === "text") {
      const text = prompt("Note text:");
      if (text) this.finish({ kind, points: [point], text });
      return;
    }
    if (!this.pending) { this.pending = point; return; }
    this.finish({ kind, points: [this.pending, point] });
  }

  finish(drawing) {
    drawing.id = `d${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
    drawing.symbol = this.pane.config.symbol;
    drawing.color = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
    this.drawings.push(drawing);
    put(`/api/drawings/${drawing.id}`, drawing).catch(() => {});
    this.pending = null;
    this.preview = null;
    this.setMode(null);
  }

  drawingNear(x, y) {
    for (const d of [...this.drawings].reverse()) {
      const pts = d.points.map((p) => ({ x: this.timeToX(p.time), y: this.pane.series.priceToCoordinate(p.price) }));
      if (pts.some((p) => p.x === null || p.y === null)) continue;
      if (d.kind === "hline" && Math.abs(pts[0].y - y) < HIT) return d;
      if (d.kind === "text" && Math.abs(pts[0].x - x) < 60 && Math.abs(pts[0].y - y) < 14) return d;
      if (pts.length === 2) {
        const [a, b] = pts;
        if (d.kind === "trend" && distanceToSegment(x, y, a, b) < HIT) return d;
        const inside = x >= Math.min(a.x, b.x) - HIT && x <= Math.max(a.x, b.x) + HIT && y >= Math.min(a.y, b.y) - HIT && y <= Math.max(a.y, b.y) + HIT;
        if ((d.kind === "rect" || d.kind === "fib") && inside) return d;
      }
    }
    return null;
  }

  remove(drawing) {
    this.drawings = this.drawings.filter((d) => d !== drawing);
    del(`/api/drawings/${drawing.id}`).catch(() => {});
    this.redraw();
  }

  clear() {
    for (const d of this.drawings) del(`/api/drawings/${d.id}`).catch(() => {});
    this.drawings = [];
    this.redraw();
  }

  // ---- Painting ------------------------------------------------------------------------

  redraw() {
    if (this.frameRequested) return;
    this.frameRequested = true;
    requestAnimationFrame(() => { this.frameRequested = false; this.paint(); });
  }

  paint() {
    if (this.pane.destroyed) return;
    const { body } = this.pane;
    const ratio = window.devicePixelRatio || 1;
    const width = body.clientWidth, height = body.clientHeight;
    if (this.canvas.width !== width * ratio || this.canvas.height !== height * ratio) {
      this.canvas.width = width * ratio;
      this.canvas.height = height * ratio;
      this.canvas.style.width = `${width}px`;
      this.canvas.style.height = `${height}px`;
    }
    const ctx = this.ctx;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    if (!this.pane.series) return;
    const priceWidth = this.pane.chart.priceScale("right").width();
    const plotWidth = width - priceWidth;
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, plotWidth, height);
    ctx.clip();
    this.paintGaps(ctx, height);
    const all = [...this.drawings];
    if (this.pending && this.preview) all.push({ kind: this.mode, points: [this.pending, this.preview], color: getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() });
    for (const d of all) this.paintDrawing(ctx, d, plotWidth);
    ctx.restore();
  }

  paintGaps(ctx, height) {
    const muted = getComputedStyle(document.documentElement).getPropertyValue("--muted").trim();
    for (const gap of this.gaps) {
      const x1 = this.timeToX(gap.from), x2 = this.timeToX(gap.to);
      if (x1 === null || x2 === null || x2 - x1 < 1) continue;
      ctx.fillStyle = "rgba(224,161,6,0.10)";          // fixed warning tint: data is missing here
      ctx.fillRect(x1, 0, x2 - x1, height);
      ctx.fillStyle = muted;
      ctx.font = "10px sans-serif";
      if (x2 - x1 > 24) ctx.fillText(`gap ${gap.missing}`, x1 + 3, 12);
    }
  }

  paintDrawing(ctx, d, plotWidth) {
    const pts = d.points.map((p) => ({ x: this.timeToX(p.time), y: this.pane.series.priceToCoordinate(p.price), price: p.price }));
    if (pts.some((p) => p.x === null || p.y === null)) return;
    ctx.strokeStyle = d.color || "#b3a1ff";
    ctx.fillStyle = d.color || "#b3a1ff";
    ctx.lineWidth = 1.5;
    if (d.kind === "hline") {
      ctx.beginPath(); ctx.moveTo(0, pts[0].y); ctx.lineTo(plotWidth, pts[0].y); ctx.stroke();
      ctx.font = "11px sans-serif"; ctx.fillText(this.pane.formatPrice(pts[0].price), 6, pts[0].y - 4);
    } else if (d.kind === "trend") {
      ctx.beginPath(); ctx.moveTo(pts[0].x, pts[0].y); ctx.lineTo(pts[1].x, pts[1].y); ctx.stroke();
    } else if (d.kind === "rect") {
      ctx.globalAlpha = 0.12;
      ctx.fillRect(pts[0].x, pts[0].y, pts[1].x - pts[0].x, pts[1].y - pts[0].y);
      ctx.globalAlpha = 1;
      ctx.strokeRect(pts[0].x, pts[0].y, pts[1].x - pts[0].x, pts[1].y - pts[0].y);
    } else if (d.kind === "fib") {
      const [a, b] = pts;
      const left = Math.min(a.x, b.x), right = Math.max(a.x, b.x, left + 40);
      ctx.font = "10px sans-serif";
      for (const level of FIB_LEVELS) {
        const price = b.price + (a.price - b.price) * level;
        const y = this.pane.series.priceToCoordinate(price);
        if (y === null) continue;
        ctx.globalAlpha = level === 0 || level === 1 ? 1 : 0.7;
        ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(right, y); ctx.stroke();
        ctx.fillText(`${level}  ${this.pane.formatPrice(price)}`, right + 4, y + 3);
      }
      ctx.globalAlpha = 1;
    } else if (d.kind === "text") {
      ctx.font = "12px sans-serif";
      const text = d.text || "";
      const width = ctx.measureText(text).width + 10;
      ctx.globalAlpha = 0.85;
      ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--panel-2").trim();
      ctx.fillRect(pts[0].x, pts[0].y - 16, width, 20);
      ctx.globalAlpha = 1;
      ctx.strokeRect(pts[0].x, pts[0].y - 16, width, 20);
      ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--text").trim();
      ctx.fillText(text, pts[0].x + 5, pts[0].y - 2);
    }
  }
}

function distanceToSegment(x, y, a, b) {
  const dx = b.x - a.x, dy = b.y - a.y;
  const length = dx * dx + dy * dy;
  const t = length ? Math.max(0, Math.min(1, ((x - a.x) * dx + (y - a.y) * dy) / length)) : 0;
  return Math.hypot(x - (a.x + t * dx), y - (a.y + t * dy));
}
