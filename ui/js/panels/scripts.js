// Scripts: the list, the floating editor (charts stay visible), running
// strategies and automations, and the Pine Script conversion helper.

import { del, get, post } from "../api.js";
import { activeAccount, refreshScripts, store } from "../store.js";
import { escapeHtml } from "../format.js";
import { toast } from "../ui.js";

const KIND_LABEL = { indicator: "Indicators", strategy: "Strategies", automation: "Automations", unknown: "Unfinished" };

const NEW_TEMPLATES = {
  indicator: `# A new indicator. calculate() runs on the chart's finished candles.
name = "My indicator"
inputs = {"length": 20}


def calculate(data):
    plot("Average", sma(data.close, inputs.length))
`,
  strategy: `# A new strategy. on_bar() runs once per finished candle.
# Signals: buy(quantity, stop=..., target=...), sell(...), close().
# Every order passes the risk guard; prop accounts need a stop loss.
name = "My strategy"
inputs = {"length": 20, "quantity": 1}


def on_bar(data, position):
    if len(data.close) < inputs.length + 1:
        return
    average = sma(data.close, inputs.length)
    price = data.close[-1]
    if position.is_flat and crossover(data.close, average):
        buy(inputs.quantity, stop=price - last(atr(data.high, data.low, data.close, 14)) * 2)
    elif position.is_long and crossunder(data.close, average):
        close()
`,
  automation: `# A new automation. run() is called at the scheduled time (weekdays),
# or on an event if you use trigger = "fill" / "alert" instead of schedule.
name = "My automation"
schedule = "09:25 America/New_York"


def run(event):
    alert("Time to check the market.")
`,
};

export function renderScripts(el, ctx) {
  const groups = {};
  for (const s of store.scripts) (groups[s.kind] ||= []).push(s);
  el.innerHTML = `
    <div class="section">
      <div class="row spread"><h3>Scripts</h3>
        <div class="row"><button class="btn small" data-new="indicator">+ Indicator</button><button class="btn small" data-new="strategy">+ Strategy</button><button class="btn small" data-new="automation">+ Automation</button></div>
      </div>
      ${Object.entries(KIND_LABEL).filter(([k]) => groups[k]).map(([k, label]) => `
        <div class="muted" style="margin:8px 0 4px">${label}</div>
        ${groups[k].map((s) => `<div class="row spread" style="padding:3px 0"><a href="#" data-open="${s.id}">${escapeHtml(s.name)}</a>
          <span class="row">${k === "indicator" ? `<button class="btn small" data-chart="${s.id}">Add to chart</button>` : ""}
          ${k === "strategy" || k === "automation" ? `<button class="btn small" data-run="${s.id}">Run on account</button>` : ""}</span></div>`).join("")}`).join("")}
    </div>
    <div class="section">
      <h3>Running strategies and automations</h3>
      <div id="runs"></div>
    </div>
    <div class="section">
      <h3>Pine Script helper</h3>
      <p class="muted">Paste a simple Pine Script indicator to convert it to Python. Anything it can't convert is kept as a comment for you to finish.</p>
      <textarea id="pine" rows="6" style="width:100%" placeholder="//@version=5&#10;indicator(&quot;My MA&quot;, overlay=true)&#10;plot(ta.sma(close, 20))"></textarea>
      <button class="btn small" id="pine-go" style="margin-top:6px">Convert</button>
    </div>`;
  el.querySelectorAll("[data-new]").forEach((b) => b.addEventListener("click", () => openEditor({ id: null, name: "", code: NEW_TEMPLATES[b.dataset.new] }, ctx)));
  el.querySelectorAll("[data-open]").forEach((a) => a.addEventListener("click", async (e) => { e.preventDefault(); openEditor(await get(`/api/scripts/${a.dataset.open}`), ctx); }));
  el.querySelectorAll("[data-chart]").forEach((b) => b.addEventListener("click", async () => {
    const ms = await ctx.activePane().addIndicator(b.dataset.chart);
    toast(`Indicator added (${ms} ms)`);
  }));
  el.querySelectorAll("[data-run]").forEach((b) => b.addEventListener("click", () => createRun(b.dataset.run, ctx, el)));
  el.querySelector("#pine-go").addEventListener("click", async () => {
    const result = await post("/api/pine/convert", { code: el.querySelector("#pine").value });
    if (result.warnings.length) toast(`Converted with ${result.warnings.length} note(s). See the comments marked TODO.`, "warning", result.warnings.slice(0, 3).join(" · "));
    openEditor({ id: null, name: result.name, code: result.code }, ctx);
  });
  paintRuns(el.querySelector("#runs"), ctx, el);
}

async function createRun(scriptId, ctx, el) {
  const account = activeAccount();
  if (!account) return toast("Choose an account first.", "blocked");
  const script = store.scripts.find((s) => s.id === scriptId);
  const pane = ctx.activePane();
  const body = { script_id: scriptId, account_id: account.id };
  if (script.kind === "strategy") { body.symbol = pane.config.symbol; body.timeframe = pane.config.timeframe; }
  try {
    const run = await post("/api/runs", body);
    await post(`/api/runs/${run.id}/start`);
    toast(`${script.name} is running on ${account.name}${body.symbol ? ` (${body.symbol} ${body.timeframe})` : ""}. Its orders still pass the risk guard.`);
  } catch (problem) {
    toast(problem.message, "blocked");
  }
  await refreshScripts();
  renderScripts(el, ctx);
}

function paintRuns(box, ctx, el) {
  if (!store.runs.length) { box.innerHTML = `<div class="muted">Nothing running. Use "Run on account" above.</div>`; return; }
  const accounts = Object.fromEntries(store.accounts.map((a) => [a.id, a]));
  box.innerHTML = `<table class="data">${store.runs.map((r) => `<tr>
    <td><strong>${escapeHtml(r.script_name)}</strong><div class="muted">${escapeHtml(accounts[r.account_id]?.name || "?")}${r.symbol ? " · " + escapeHtml(r.symbol) + " " + r.timeframe : ""}</div>
      ${r.last_error ? `<div class="message blocked">${escapeHtml(r.last_error.message)}</div>` : ""}
      ${r.messages?.length ? `<details><summary>Messages</summary>${r.messages.map((m) => `<div class="muted">${escapeHtml(m)}</div>`).join("")}</details>` : ""}</td>
    <td>${r.active ? '<span class="badge ok">running</span>' : `<span class="muted">${escapeHtml(r.status)}</span>`}</td>
    <td class="row">${r.active ? `<button class="btn small" data-stop="${r.id}">Stop</button>` : `<button class="btn small" data-start="${r.id}">Start</button>`}
      <button class="btn small" data-delete="${r.id}">✕</button></td></tr>`).join("")}</table>`;
  const act = async (fn) => { try { await fn(); } catch (p) { toast(p.message, "blocked"); } await refreshScripts(); renderScripts(el, ctx); };
  box.querySelectorAll("[data-stop]").forEach((b) => b.addEventListener("click", () => act(() => post(`/api/runs/${b.dataset.stop}/stop`))));
  box.querySelectorAll("[data-start]").forEach((b) => b.addEventListener("click", () => act(() => post(`/api/runs/${b.dataset.start}/start`))));
  box.querySelectorAll("[data-delete]").forEach((b) => b.addEventListener("click", () => act(() => del(`/api/runs/${b.dataset.delete}`))));
}

// ---- The floating editor --------------------------------------------------------

let editor = null;

export function openEditor(script, ctx) {
  document.querySelector(".floating.editor")?.remove();
  const box = document.createElement("div");
  box.className = "floating editor glow";
  box.innerHTML = `
    <div class="float-head">
      <input type="text" id="e-name" placeholder="Script name" value="${escapeHtml(script.name)}" style="flex:1">
      <button class="btn small" id="e-check">Check</button>
      <button class="btn small primary" id="e-save">Save</button>
      <button class="btn small" id="e-chart">Add to chart</button>
      <button class="btn small" id="e-test">Backtest</button>
      ${script.id && !script.id.startsWith("example_") ? `<button class="btn small" id="e-delete">Delete</button>` : ""}
      <button class="btn icon small" id="e-close" title="Close">✕</button>
    </div>
    <div class="float-body"><textarea id="e-code"></textarea></div>
    <div class="float-foot" id="e-foot"><span class="muted">Ctrl+S saves. Errors appear here in plain English.</span></div>`;
  document.body.appendChild(box);
  editor = window.CodeMirror.fromTextArea(box.querySelector("#e-code"), { mode: "python", lineNumbers: true, indentUnit: 4, tabSize: 4, indentWithTabs: false, extraKeys: { Tab: (cm) => cm.replaceSelection("    "), "Ctrl-S": () => save() } });
  editor.setValue(script.code);
  let current = { ...script };
  let errorLine = null;

  const foot = box.querySelector("#e-foot");
  const showCheck = (check) => {
    if (errorLine !== null) editor.removeLineClass(errorLine, "background", "cm-error-line");
    errorLine = null;
    if (check.ok) {
      foot.innerHTML = `<div class="message ok">Looks good: a${check.type === "indicator" ? "n" : ""} ${check.type}${check.name ? ` called "${escapeHtml(check.name)}"` : ""}${Object.keys(check.inputs || {}).length ? ` with inputs ${escapeHtml(Object.keys(check.inputs).join(", "))}` : ""}.</div>`;
      return;
    }
    const err = check.error;
    if (err.line) { errorLine = err.line - 1; editor.addLineClass(errorLine, "background", "cm-error-line"); editor.scrollIntoView({ line: errorLine, ch: 0 }); }
    foot.innerHTML = `<div class="message blocked">${escapeHtml(err.message)}</div>${err.details ? `<details><summary>Show the technical details</summary><pre class="details">${escapeHtml(err.details)}</pre></details>` : ""}`;
  };

  const save = async () => {
    const result = await post("/api/scripts", { id: current.id, name: box.querySelector("#e-name").value, code: editor.getValue() });
    current = result.script;
    showCheck(result.check);
    await refreshScripts();
    ctx.rerenderDock();
    if (result.check.ok) toast(`Saved "${current.name}"`);
    return result;
  };

  box.querySelector("#e-check").addEventListener("click", async () => showCheck(await post("/api/scripts/check", { code: editor.getValue() })));
  box.querySelector("#e-save").addEventListener("click", save);
  box.querySelector("#e-close").addEventListener("click", () => box.remove());
  box.querySelector("#e-chart").addEventListener("click", async () => {
    const result = await save();
    if (!result.check.ok) return;
    if (result.check.type !== "indicator") return toast("Only indicators go on charts. Strategies are backtested or run on an account.", "warning");
    const ms = await ctx.activePane().addIndicator(current.id);
    toast(`Added to the active chart (${ms} ms)`);
  });
  box.querySelector("#e-test").addEventListener("click", async () => {
    const result = await save();
    if (!result.check.ok) return;
    if (result.check.type !== "strategy") return toast("Backtests need a strategy (a script with on_bar).", "warning");
    ctx.openBacktest(current.id);
  });
  box.querySelector("#e-delete")?.addEventListener("click", async () => {
    if (!confirm(`Delete "${current.name}"?`)) return;
    await del(`/api/scripts/${current.id}`);
    box.remove();
    await refreshScripts();
    ctx.rerenderDock();
  });

  // Drag the editor by its header.
  const head = box.querySelector(".float-head");
  head.addEventListener("pointerdown", (e) => {
    if (e.target.closest("button,input")) return;
    const rect = box.getBoundingClientRect();
    const dx = e.clientX - rect.left, dy = e.clientY - rect.top;
    const move = (ev) => { box.style.left = `${ev.clientX - dx}px`; box.style.top = `${Math.max(0, ev.clientY - dy)}px`; box.style.right = "auto"; };
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  });
  setTimeout(() => editor.refresh(), 0);
}
