"""The jobs a script worker can do. This code runs INSIDE the sandboxed worker process.

Script types are recognised by the function they define:
    calculate(data)            an indicator: draws on the chart
    on_bar(data, position)     a strategy: returns buy/sell/close signals
    run(event)                 an automation: reacts to a time or an event

Optional script settings:
    name = "My script"
    inputs = {"length": 20}    values the owner can change without editing code (scripts use inputs.length)
    lookback = 300             how many candles a strategy sees on each bar (default 300)
    use_live_candles = True    let the script see the unfinished candle too (reports say so)
    schedule = "09:30 America/New_York"   for automations: run daily at this time
    trigger = "fill"           for automations: run on an event (fill, alert, daily_reset)
"""

import hashlib
import math

import numpy as np

from engine.scripting import library
from engine.scripting.sandbox import compile_script

DEFAULT_LOOKBACK = 300


class Inputs(dict):
    """Lets scripts write inputs.length as well as inputs["length"]."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(f"There is no input called '{name}'. Add it to the inputs dictionary at the top of the script.")


def script_type(namespace: dict) -> str:
    if callable(namespace.get("calculate")):
        return "indicator"
    if callable(namespace.get("on_bar")):
        return "strategy"
    if callable(namespace.get("run")):
        return "automation"
    return "unknown"


def describe(namespace: dict) -> dict:
    inputs = namespace.get("inputs", {})
    return {
        "type": script_type(namespace),
        "name": str(namespace.get("name", "")),
        "inputs": dict(inputs) if isinstance(inputs, dict) else {},
        "lookback": int(namespace.get("lookback", DEFAULT_LOOKBACK)),
        "use_live_candles": bool(namespace.get("use_live_candles", False)),
        "schedule": namespace.get("schedule"),
        "trigger": namespace.get("trigger"),
    }


def _prepare(code: str, overrides: dict | None) -> dict:
    namespace = compile_script(code)
    base = namespace.get("inputs", {}) if isinstance(namespace.get("inputs"), dict) else {}
    namespace["inputs"] = Inputs({**base, **(overrides or {})})
    return namespace


def _data(arrays: dict, symbol: str = "", timeframe: str = "") -> library.Data:
    return library.Data(
        np.asarray(arrays["time"]), np.asarray(arrays["open"], dtype=float), np.asarray(arrays["high"], dtype=float),
        np.asarray(arrays["low"], dtype=float), np.asarray(arrays["close"], dtype=float), np.asarray(arrays["volume"], dtype=float),
        symbol, timeframe,
    )


def _clean_values(values) -> list:
    out = []
    for v in np.asarray(values, dtype=float).tolist():
        out.append(None if (v is None or math.isnan(v) or math.isinf(v)) else round(v, 8))
    return out


def run(job: dict, sessions: dict, heartbeat) -> dict:
    kind = job["kind"]
    if kind == "ping":
        return {"pong": True}

    if kind == "describe":
        return describe(compile_script(job["code"]))

    if kind == "indicator":
        namespace = _prepare(job["code"], job.get("inputs"))
        if script_type(namespace) != "indicator":
            raise ValueError("An indicator needs a calculate(data) function")
        library._outputs = library.Outputs()
        data = _data(job["data"], job.get("symbol", ""), job.get("timeframe", ""))
        namespace["calculate"](data)
        count = len(data)
        plots = []
        for p in library._outputs.plots:
            values = p["values"]
            if values.ndim == 0:
                values = np.full(count, float(values))
            if len(values) != count:
                raise ValueError(f"plot('{p['name']}') got {len(values)} values but there are {count} candles. Plot one value per candle")
            plots.append({**p, "values": _clean_values(values)})
        return {"plots": plots, "lines": library._outputs.lines, "messages": library._outputs.messages[-50:]}

    if kind == "backtest":
        from engine.core.markets import Market
        from engine.strategy.backtest_core import run_backtest

        namespace = _prepare(job["code"], job.get("inputs"))
        if script_type(namespace) != "strategy":
            raise ValueError("A backtest needs a strategy script with an on_bar(data, position) function")
        info = describe(namespace)
        market = Market(**job["market"])
        on_bar = namespace["on_bar"]

        def call(window, size, entry):
            library._outputs = library.Outputs()
            on_bar(_data(window, job.get("symbol", ""), job.get("timeframe", "")), library.PositionView(size, entry))
            return library._outputs.signals

        report = run_backtest(call, job["data"], market, job.get("starting_balance", 25000.0), info["lookback"], heartbeat)
        report["used_live_candles"] = info["use_live_candles"]
        report["script"] = info
        return report

    if kind == "strategy_bar":
        key = job["session"] + hashlib.sha1(job["code"].encode()).hexdigest()
        if key not in sessions:
            sessions[key] = _prepare(job["code"], job.get("inputs"))
        namespace = sessions[key]
        library._outputs = library.Outputs()
        namespace["on_bar"](_data(job["data"], job.get("symbol", ""), job.get("timeframe", "")), library.PositionView(job.get("size", 0.0), job.get("entry", 0.0)))
        return {"signals": library._outputs.signals, "messages": library._outputs.messages[-20:]}

    if kind == "automation":
        key = job["session"] + hashlib.sha1(job["code"].encode()).hexdigest()
        if key not in sessions:
            sessions[key] = _prepare(job["code"], job.get("inputs"))
        namespace = sessions[key]
        library._outputs = library.Outputs()
        namespace["run"](job.get("event", {}))
        return {"signals": library._outputs.signals, "messages": library._outputs.messages[-20:]}

    raise ValueError(f"Unknown job '{kind}'")
