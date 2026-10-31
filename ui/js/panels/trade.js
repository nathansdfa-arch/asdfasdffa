// Order ticket, positions and working orders for the active account.
// Clearly labelled PAPER or LIVE. Every order goes through the risk guard.

import { post } from "../api.js";
import { activeAccount, market, store } from "../store.js";
import { escapeHtml, money, price as fmtPrice, signed } from "../format.js";
import { showResult } from "../ui.js";

export function renderTrade(el, ctx) {
  const account = activeAccount();
  const symbol = ctx.activeSymbol();
  const m = market(symbol) || {};
  store.ticket = store.ticket || { quantity: m.min_quantity || 1, stopTicks: 20, targetTicks: 40, side: "buy", type: "market" };
  const t = store.ticket;
  const live = account?.mode === "LIVE";
  el.innerHTML = `
    <div class="section">
      <div class="row spread"><h3>Order ticket</h3><span class="badge ${live ? "live" : "paper"}">${live ? "LIVE" : "PAPER"}</span></div>
      <div class="stack">
        <div class="row"><strong>${escapeHtml(symbol)}</strong><span class="muted">${escapeHtml(m.name || "")}</span></div>
        <div class="row">
          <button class="btn buy ${t.side === "buy" ? "active" : ""}" data-side="buy">Buy</button>
          <button class="btn sell ${t.side === "sell" ? "active" : ""}" data-side="sell">Sell</button>
          <select id="t-type"><option value="market">Market</option><option value="limit">Limit</option><option value="stop">Stop</option></select>
        </div>
        <div class="grid2">
          <label class="field">Quantity<input id="t-qty" type="number" step="${m.quantity_step || 1}" min="${m.min_quantity || 0}" value="${t.quantity}"></label>
          <label class="field">Price (limit/stop)<input id="t-price" type="number" step="${m.tick_size || 0.01}" placeholder="—"></label>
          <label class="field">Stop loss (ticks away)<input id="t-stop" type="number" min="0" value="${t.stopTicks}"></label>
          <label class="field">Target (ticks away, 0 = none)<input id="t-target" type="number" min="0" value="${t.targetTicks}"></label>
        </div>
        <div id="t-preview" class="muted"></div>
        <button class="btn primary" id="t-send">Send order</button>
        <div id="t-result"></div>
      </div>
    </div>
    <div class="section">
      <div class="row spread"><h3>Positions</h3>${account ? `<button class="btn small" id="flatten">Close all</button>` : ""}</div>
      <div id="positions"></div>
    </div>
    <div class="section">
      <h3>Working orders</h3>
      <div id="orders"></div>
    </div>`;
  el.querySelector("#t-type").value = t.type;
  el.querySelectorAll("[data-side]").forEach((b) => b.addEventListener("click", () => { t.side = b.dataset.side; renderTrade(el, ctx); }));
  const read = () => {
    t.type = el.querySelector("#t-type").value;
    t.quantity = Number(el.querySelector("#t-qty").value);
    t.stopTicks = Number(el.querySelector("#t-stop").value) || 0;
    t.targetTicks = Number(el.querySelector("#t-target").value) || 0;
    preview();
  };
  const preview = () => {
    const last = store.prices[symbol];
    const entry = t.type === "market" ? last : Number(el.querySelector("#t-price").value) || last;
    const box = el.querySelector("#t-preview");
    if (!entry || !m.tick_size) { box.textContent = "Waiting for a price…"; return; }
    const risk = t.stopTicks * m.tick_size * m.point_value * t.quantity;
    const sign = t.side === "buy" ? 1 : -1;
    box.innerHTML = `Entry ≈ <span class="num">${fmtPrice(entry, symbol)}</span> · Stop <span class="num">${fmtPrice(entry - sign * t.stopTicks * m.tick_size, symbol)}</span> · Risk to stop ≈ <span class="num">${money(risk)}</span> before fees and slippage`;
  };
  el.querySelectorAll("#t-type,#t-qty,#t-stop,#t-target,#t-price").forEach((i) => i.addEventListener("input", read));
  preview();
  ctx.onPrice = preview;

  el.querySelector("#t-send").addEventListener("click", async () => {
    read();
    if (!account) return;
    const tick = m.tick_size;
    const sign = t.side === "buy" ? 1 : -1;
    const typed = Number(el.querySelector("#t-price").value);
    const entry = t.type === "market" ? store.prices[symbol] : typed;
    if (t.type !== "market" && !typed) { el.querySelector("#t-result").innerHTML = `<div class="message blocked">Enter a price for a ${t.type} order.</div>`; return; }
    const round = (v) => Number((Math.round(v / tick) * tick).toFixed(10));
    const body = {
      account_id: account.id, symbol, side: t.side, quantity: t.quantity, order_type: t.type,
      price: t.type === "market" ? null : typed,
      stop_loss: t.stopTicks && entry ? round(entry - sign * t.stopTicks * tick) : null,
      take_profit: t.targetTicks && entry ? round(entry + sign * t.targetTicks * tick) : null,
    };
    const result = await post("/api/orders", body).catch((p) => ({ ok: false, message: p.message }));
    el.querySelector("#t-result").innerHTML = `<div class="message ${result.ok ? "ok" : "blocked"}">${result.ok ? "Approved and sent." : "Blocked: " + escapeHtml(result.message)}<div class="muted">${escapeHtml(result.decision?.rule || "")}</div></div>`;
    showResult(result, "Order sent");
    window.dispatchEvent(new Event("trading-changed"));
  });

  el.querySelector("#flatten")?.addEventListener("click", async () => {
    const result = await post(`/api/accounts/${account.id}/flatten`);
    showResult({ ok: true, message: `Cancelled ${result.cancelled} order(s), closed ${result.closed} position(s).` });
    window.dispatchEvent(new Event("trading-changed"));
  });
  paintTables(el, account);
}

export function paintTables(el, account) {
  const positions = el.querySelector("#positions");
  const orders = el.querySelector("#orders");
  if (!positions || !orders) return;
  if (!account) { positions.innerHTML = `<div class="muted">No account selected.</div>`; orders.innerHTML = ""; return; }
  const rows = (account.positions || []).map((p) => {
    const m = market(p.symbol) || { point_value: 1 };
    const now = store.prices[p.symbol] ?? p.price;
    const pnl = now !== null && now !== undefined ? (now - p.average_price) * p.quantity * m.point_value : null;
    return `<tr><td>${escapeHtml(p.symbol)}</td><td class="num ${p.quantity > 0 ? "up" : "down"}">${p.quantity > 0 ? "+" : ""}${p.quantity}</td>
      <td class="num">${fmtPrice(p.average_price, p.symbol)}</td><td class="num ${pnl >= 0 ? "up" : "down"}">${signed(pnl)}</td>
      <td class="num">${p.stop !== null ? fmtPrice(p.stop, p.symbol) : '<span class="badge warn">none</span>'}</td>
      <td><button class="btn small" data-close="${escapeHtml(p.symbol)}">Close</button></td></tr>`;
  }).join("");
  positions.innerHTML = rows ? `<table class="data"><tr><th>Symbol</th><th>Qty</th><th>Avg</th><th>P&L</th><th>Stop</th><th></th></tr>${rows}</table>` : `<div class="muted">Flat. No open positions.</div>`;
  positions.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", async () => {
    const result = await post("/api/positions/close", { account_id: account.id, symbol: b.dataset.close }).catch((p) => ({ ok: false, message: p.message }));
    showResult(result, `Closing ${b.dataset.close}`);
    window.dispatchEvent(new Event("trading-changed"));
  }));
  const orderRows = (account.orders || []).map((o) => `<tr><td>${escapeHtml(o.symbol)}</td><td>${o.role === "entry" ? o.side + " " + o.order_type : o.role.replace("_", " ")}</td>
      <td class="num">${o.quantity}</td><td class="num">${o.price !== null ? fmtPrice(o.price, o.symbol) : "market"}</td>
      <td>${o.role === "stop_loss" ? '<span class="muted">move on chart</span>' : `<button class="btn small" data-cancel="${o.id}">Cancel</button>`}</td></tr>`).join("");
  orders.innerHTML = orderRows ? `<table class="data"><tr><th>Symbol</th><th>Type</th><th>Qty</th><th>Price</th><th></th></tr>${orderRows}</table>` : `<div class="muted">No working orders.</div>`;
  orders.querySelectorAll("[data-cancel]").forEach((b) => b.addEventListener("click", async () => {
    const result = await post("/api/orders/cancel", { account_id: account.id, order_id: b.dataset.cancel }).catch((p) => ({ ok: false, message: p.message }));
    showResult(result, "Order cancelled");
    window.dispatchEvent(new Event("trading-changed"));
  }));
}
