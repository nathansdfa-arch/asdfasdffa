"""Runs strategies and automations live (paper or live accounts).

Strategies: on every finished candle of their symbol and timeframe, the
strategy sees the latest candles and returns signals. Signals become order
requests (engine/strategy/signals.py, the same rules as backtests) and go
through the order service, so the risk guard checks every one.

Automations: run at a scheduled time each weekday, or when an event happens
(a fill, an alert, the daily reset). They can show alerts and send orders,
which are also checked by the risk guard.

The kill switch stops every strategy and automation at once.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from engine.core.models import OrderRequest, timeframe_seconds
from engine.scripting.host import candle_arrays
from engine.scripting.sandbox import ScriptError, ScriptWorker
from engine.storage.database import connect, utc_now
from engine.strategy.signals import plan_orders

log = logging.getLogger(__name__)

DEFAULT_LOOKBACK = 300


class RunStore:
    """Saved strategy and automation runs, so they come back after a restart (stopped, for safety)."""

    def __init__(self, db_path):
        self.db_path = db_path

    def all(self) -> list[dict]:
        with connect(self.db_path) as conn:
            return [json.loads(row["config"]) for row in conn.execute("SELECT config FROM runs ORDER BY updated_at")]

    def save(self, run: dict) -> None:
        with connect(self.db_path) as conn:
            conn.execute("INSERT OR REPLACE INTO runs (id, config, updated_at) VALUES (?, ?, ?)", (run["id"], json.dumps(run), utc_now()))

    def delete(self, run_id: str) -> None:
        with connect(self.db_path) as conn:
            conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))


class Runner:
    def __init__(self, scripts, data, orders, accounts, catalog, guard, bus, runs: RunStore, clock):
        self.scripts = scripts
        self.data = data
        self.orders = orders
        self.accounts = accounts
        self.catalog = catalog
        self.guard = guard
        self.bus = bus
        self.store = runs
        self.clock = clock
        self.runs: dict[str, dict] = {}
        self.workers: dict[str, ScriptWorker] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        for run in runs.all():
            run["active"] = False          # after a restart everything starts switched off
            run["status"] = "stopped (app restarted)"
            self.runs[run["id"]] = run
        bus.subscribe("candle", self._on_candle)
        bus.subscribe("fill", lambda topic, fill: self._on_event("fill", fill))
        bus.subscribe("alert", lambda topic, alert: self._on_event("alert", alert))

    # ---- Managing runs ------------------------------------------------------

    def create(self, script_id: str, account_id: str, symbol: str | None, timeframe: str | None, inputs: dict | None) -> dict:
        script = self.scripts.get(script_id)
        if script["kind"] not in ("strategy", "automation"):
            raise ValueError("Only strategies and automations can run on an account. Indicators are added to charts.")
        self.accounts.get(account_id)
        if script["kind"] == "strategy":
            if not symbol or not timeframe:
                raise ValueError("A strategy needs a symbol and a timeframe.")
            self.catalog.get(symbol)
            timeframe_seconds(timeframe)
        run = {
            "id": uuid.uuid4().hex[:10], "script_id": script_id, "script_name": script["name"], "kind": script["kind"],
            "account_id": account_id, "symbol": symbol, "timeframe": timeframe, "inputs": inputs or {},
            "active": False, "status": "stopped", "last_error": None, "messages": [], "last_run_day": None,
        }
        self.runs[run["id"]] = run
        self.store.save(run)
        return run

    def start(self, run_id: str) -> dict:
        run = self.runs[run_id]
        if self.guard.trading_halted:
            raise ValueError("Trading is halted by the kill switch. Switch trading back on first.")
        run["active"] = True
        run["status"] = "running"
        run["last_error"] = None
        if run["kind"] == "strategy":
            self.data.want_live(run["symbol"], run["timeframe"])
        else:
            # Don't fire straight away for a time that already passed today.
            schedule = self._schedule(run)
            if schedule:
                local = datetime.fromtimestamp(self.clock(), tz=timezone.utc).astimezone(ZoneInfo(schedule[1]))
                if local.strftime("%H:%M") >= schedule[0]:
                    run["last_run_day"] = local.date().isoformat()
        self.guard.resume_source(self._source(run))
        self.store.save(run)
        self._publish(run)
        return run

    def stop(self, run_id: str, reason: str = "stopped") -> dict:
        run = self.runs[run_id]
        run["active"] = False
        run["status"] = reason
        self.store.save(run)
        worker = self.workers.pop(run_id, None)
        if worker:
            worker.close()
        self._publish(run)
        return run

    def stop_all(self) -> None:
        for run_id, run in self.runs.items():
            if run["active"]:
                self.stop(run_id, "stopped by the kill switch")

    def delete(self, run_id: str) -> None:
        self.stop(run_id)
        self.runs.pop(run_id, None)
        self.store.delete(run_id)

    def all(self) -> list[dict]:
        return list(self.runs.values())

    def _source(self, run: dict) -> str:
        return f"{'script' if run['kind'] == 'strategy' else 'automation'}:{run['script_name']}"

    def _publish(self, run: dict) -> None:
        self.bus.publish("run", {k: run[k] for k in ("id", "active", "status", "last_error", "script_name")})

    def _worker(self, run_id: str) -> ScriptWorker:
        if run_id not in self.workers:
            self.workers[run_id] = ScriptWorker(f"run-{run_id}")
        return self.workers[run_id]

    # ---- Strategies ---------------------------------------------------------

    def _on_candle(self, topic: str, message: dict) -> None:
        if not message.get("finished") or self._loop is None:
            return
        for run in list(self.runs.values()):
            if run["active"] and run["kind"] == "strategy" and run["symbol"] == message["symbol"] and run["timeframe"] == message["timeframe"]:
                self._loop.create_task(self.step_strategy(run["id"]))

    async def step_strategy(self, run_id: str) -> list[dict]:
        """Run one strategy on the latest finished candles and send its signals."""
        run = self.runs.get(run_id)
        if not run or not run["active"]:
            return []
        script = self.scripts.get(run["script_id"])
        seconds = timeframe_seconds(run["timeframe"])
        now = self.clock()
        lookback = DEFAULT_LOOKBACK
        history = self.data.cache.read(run["symbol"], run["timeframe"], int(now - seconds * (lookback + 50)), int(now))
        candles = history[-lookback:]
        if "use_live_candles = True" in script["code"]:
            forming = self.data.feeds.get(run["symbol"])
            if forming and run["timeframe"] in forming.forming:
                candles = candles + [forming.forming[run["timeframe"]]]
        if not candles:
            return []
        account = self.accounts.get(run["account_id"])
        broker = self.orders.broker_for(account)
        position = broker.position(account.id, run["symbol"])
        job = {
            "kind": "strategy_bar", "session": run_id, "code": script["code"], "data": candle_arrays(candles),
            "symbol": run["symbol"], "timeframe": run["timeframe"], "inputs": run["inputs"],
            "size": position.quantity, "entry": position.average_price,
        }
        try:
            result = await asyncio.to_thread(self._worker(run_id).call, job)
        except ScriptError as problem:
            run["last_error"] = problem.info
            self.stop(run_id, "stopped after an error")
            self.guard.alert("warning", f"Strategy '{run['script_name']}' stopped: {problem.info['message']}", account.id)
            return []
        if not run["active"]:
            return []     # stopped (e.g. kill switch) while it was thinking
        return self._send_signals(run, result)

    def _send_signals(self, run: dict, result: dict) -> list[dict]:
        outcomes = []
        for message in result.get("messages", []):
            run["messages"] = (run["messages"] + [message])[-20:]
            self.guard.alert("info", f"{run['script_name']}: {message}", run["account_id"])
        for signal in result.get("signals", []):
            symbol = signal.get("symbol") or run.get("symbol")
            if not symbol:
                outcomes.append({"ok": False, "message": "The automation sent an order without a symbol."})
                continue
            account = self.accounts.get(run["account_id"])
            position = self.orders.broker_for(account).position(account.id, symbol)
            for planned in plan_orders(signal, position.quantity):
                request = OrderRequest(
                    account_id=run["account_id"], symbol=symbol, side=planned.side, quantity=planned.quantity,
                    order_type=planned.order_type, price=planned.price, stop_loss=planned.stop_loss,
                    take_profit=planned.take_profit, reduce_only=planned.reduce_only, source=self._source(run),
                )
                outcome = self.orders.submit(request)
                outcomes.append(outcome)
                if not outcome["ok"]:
                    run["messages"] = (run["messages"] + [f"Blocked: {outcome['message']}"])[-20:]
        self.store.save(run)
        self._publish(run)
        return outcomes

    # ---- Automations --------------------------------------------------------

    def _on_event(self, kind: str, details: dict) -> None:
        if self._loop is None:
            return
        for run in list(self.runs.values()):
            if run["active"] and run["kind"] == "automation":
                script = self.scripts.get(run["script_id"])
                if f'trigger = "{kind}"' in script["code"] or f"trigger = '{kind}'" in script["code"]:
                    self._loop.create_task(self.run_automation(run["id"], {"type": kind, "details": details}))

    async def run_automation(self, run_id: str, event: dict) -> list[dict]:
        run = self.runs.get(run_id)
        if not run or not run["active"]:
            return []
        script = self.scripts.get(run["script_id"])
        job = {"kind": "automation", "session": run_id, "code": script["code"], "event": event, "inputs": run["inputs"]}
        try:
            result = await asyncio.to_thread(self._worker(run_id).call, job)
        except ScriptError as problem:
            run["last_error"] = problem.info
            self.stop(run_id, "stopped after an error")
            self.guard.alert("warning", f"Automation '{run['script_name']}' stopped: {problem.info['message']}", run["account_id"])
            return []
        if not run["active"]:
            return []
        return self._send_signals(run, result)

    def due_automations(self, unix_time: float) -> list[str]:
        """Automations whose daily schedule time has arrived (weekdays only) and haven't run today."""
        due = []
        for run in self.runs.values():
            if not (run["active"] and run["kind"] == "automation"):
                continue
            schedule = self._schedule(run)
            if not schedule:
                continue
            hhmm, tz = schedule
            local = datetime.fromtimestamp(unix_time, tz=timezone.utc).astimezone(ZoneInfo(tz))
            if local.weekday() >= 5:
                continue
            today = local.date().isoformat()
            if run.get("last_run_day") == today:
                continue
            if local.strftime("%H:%M") >= hhmm:
                run["last_run_day"] = today
                self.store.save(run)
                due.append(run["id"])
        return due

    def _schedule(self, run: dict) -> tuple[str, str] | None:
        import re
        code = self.scripts.get(run["script_id"])["code"]
        match = re.search(r'^schedule\s*=\s*["\'](\d{1,2}:\d{2})\s*([\w/_+-]*)["\']', code, re.M)
        if not match:
            return None
        hhmm = match.group(1).zfill(5)
        return hhmm, match.group(2) or "UTC"

    async def start_scheduler(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.create_task(self._scheduler())

    async def _scheduler(self) -> None:
        while True:
            for run_id in self.due_automations(self.clock()):
                await self.run_automation(run_id, {"type": "schedule", "time": self.clock()})
            await asyncio.sleep(1)

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
        for worker in self.workers.values():
            worker.close()
        self.workers.clear()
