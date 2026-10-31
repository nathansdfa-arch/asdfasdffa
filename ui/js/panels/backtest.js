// Backtests: pick a strategy, symbol, timeframe and period; see the report the
// bible asks for (net profit, win rate, max drawdown, average win and loss,
// equity curve) and the trades on the chart.

import { post } from "../api.js";
import { store } from "../store.js";
import { escapeHtml, money, time as fmtTime } from "../format.js";
import { chartColors } from "../themes.js";

let lastReport = null;

export function renderBacktest(el, ctx, scriptId = null) {
  const strategies = store.scripts.filter((s) => s.kind === "strategy");
  const pane = ctx.activePane();
  el.innerHTML = `
    <div class="section">
      <h3>Backtest</h3>
      <div class="stack">
        <label class="field">Strategy<select id="b-script">${strategies.map((s) => `<option value="${s.id}" ${s.id === scriptId ? "selected" : ""}>${escapeHtml(s.name)}</option>`).join("")}</select></label>
        <div class="grid2">
          <label class="field">Symbol<select id="b-symbol">${Object.keys(store.markets).map((s) => `<option ${s === pane.config.symbol ? "selected" : ""}>${s}</option>`).join("")}</select></label>
          <label class="field">Timeframe<select id="b-tf">${["1m", "5m", "15m", "1h", "4h", "1d"].map((t) => `<option ${t === pane.config.timeframe ? "selected" : ""}>${t}</option>`).join("")}</select></label>
          <label class="field">Days of history<input id="b-days" type="number" value="30" min="1"></label>
          <label class="field">Starting balance<input id="b-balance" type="number" value="25000"></label>
        </div>
        <button class="btn primary" id="b-run">Run backtest</button>
        <div id="b-status" class="muted">Uses the same fill model as paper trading: next-candle fills, slippage and fees from config/markets.json.</div>
      </div>
    </div>
    <div id="b-report"></div>`;
  el.querySelector("#b-run").addEventListener("click", async () => {
    const status = el.querySelector("#b-status");
    status.textContent = "Running…";
    const started = performance.now();
    const result = await post("/api/backtest", {
      script_id: el.querySelector("#b-script").value, symbol: el.querySelector("#b-symbol").value,
      timeframe: el.querySelector("#b-tf").value, days: Number(el.querySelector("#b-days").value),
      starting_balance: Number(el.querySelector("#b-balance").value),
    }).catch((p) => ({ ok: false, error: { message: p.message } }));
    if (!result.ok) { status.innerHTML = `<div class="message blocked">${escapeHtml(result.error.message)}</div>`; return; }
    status.textContent = `Done in ${((performance.now() - started) / 1000).toFixed(1)} s over ${result.report.candles.toLocaleString()} candles.`;
    lastReport = result.report;
    paintReport(el.querySelector("#b-report"), result.report, ctx);
  });
  if (lastReport) paintReport(el.querySelector("#b-report"), lastReport, ctx);
}

function paintReport(box, r, ctx) {
  const stat = (label, value, cls = "") => `<div class="stat"><div class="muted" style="font-size:11px">${label}</div><div class="num ${cls}" style="font-size:15px">${value}</div></div>`;
  box.innerHTML = `
    <div class="section">
      <h3>${escapeHtml(r.script?.name || "Report")} · ${escapeHtml(r.symbol)} ${r.timeframe}</h3>
      <div class="muted">${fmtTime(r.from)} to ${fmtTime(r.to)}${r.used_live_candles ? ' · <span class="badge warn">used unfinished candles</span>' : ""}</div>
      <div class="grid3" style="margin:10px 0">
        ${stat("Net profit", money(r.net_profit), r.net_profit >= 0 ? "up" : "down")}
        ${stat("Win rate", `${r.win_rate}%`)}
        ${stat("Max drawdown", `${money(r.max_drawdown)} (${r.max_drawdown_percent}%)`, "down")}
        ${stat("Average win", money(r.average_win), "up")}
        ${stat("Average loss", money(r.average_loss), "down")}
        ${stat("Trades", r.total_trades)}
        ${stat("Profit factor", r.profit_factor ?? "–")}
        ${stat("Fees paid", money(r.fees_paid))}
        ${stat("Final equity", money(r.final_equity))}
      </div>
      <div id="equity" style="height:160px;position:relative"></div>
      <div class="row" style="margin-top:8px"><button class="btn small" id="show-trades">Show trades on the active chart</button></div>
    </div>
    <div class="section"><h3>Trades</h3>
      <table class="data"><tr><th>Side</th><th>Entry</th><th>Exit</th><th>P&L</th><th>Why</th></tr>
      ${r.trades.slice(-200).reverse().map((t) => `<tr><td>${t.side}</td><td class="num">${fmtTime(t.entry_time)}<br>${t.entry_price}</td><td class="num">${t.exit_time ? fmtTime(t.exit_time) + "<br>" + t.exit_price : "open"}</td><td class="num ${t.pnl >= 0 ? "up" : "down"}">${money(t.pnl)}</td><td class="muted">${escapeHtml(t.exit_reason || "")}</td></tr>`).join("")}
      </table></div>`;
  const colors = chartColors(store.settings);
  const LC = window.LightweightCharts;
  const chart = LC.createChart(box.querySelector("#equity"), {
    autoSize: true, layout: { background: { type: LC.ColorType.Solid, color: "rgba(0,0,0,0)" }, textColor: colors.text, attributionLogo: true },
    grid: { vertLines: { visible: false }, horzLines: { color: colors.grid } }, timeScale: { borderColor: colors.border }, rightPriceScale: { borderColor: colors.border },
  });
  const series = chart.addSeries(LC.AreaSeries, { lineColor: colors.accent, topColor: colors.accent + "55", bottomColor: colors.accent + "05", lineWidth: 2 });
  series.setData(r.equity_curve.map((p) => ({ time: p.time, value: p.value })));
  chart.timeScale().fitContent();
  box.querySelector("#show-trades").addEventListener("click", () => {
    const pane = ctx.activePane();
    if (pane.config.symbol !== r.symbol || pane.config.timeframe !== r.timeframe) {
      pane.config.symbol = r.symbol;
      pane.config.timeframe = r.timeframe;
      pane.load().then(() => pane.showBacktestTrades(r.trades));
    } else pane.showBacktestTrades(r.trades);
  });
}
