"""The script host: runs indicators and backtests in sandboxed workers on the engine's behalf."""

import asyncio
import logging
from dataclasses import asdict

import numpy as np

from engine.core.markets import MarketCatalog
from engine.core.models import Candle
from engine.scripting.sandbox import ScriptError, ScriptWorker

log = logging.getLogger(__name__)

BACKTEST_SILENCE_LIMIT = 2.0   # a backtest that stops reporting progress for this long is stopped


def candle_arrays(candles: list[Candle]) -> dict:
    return {
        "time": np.array([c.time for c in candles], dtype=np.int64),
        "open": np.array([c.open for c in candles]),
        "high": np.array([c.high for c in candles]),
        "low": np.array([c.low for c in candles]),
        "close": np.array([c.close for c in candles]),
        "volume": np.array([c.volume for c in candles]),
    }


class ScriptHost:
    def __init__(self, catalog: MarketCatalog):
        self.catalog = catalog
        self.indicator_worker = ScriptWorker("indicators")
        self.backtest_worker = ScriptWorker("backtests")

    async def describe(self, code: str) -> dict:
        try:
            info = await asyncio.to_thread(self.indicator_worker.call, {"kind": "describe", "code": code})
            return {"ok": True, **info}
        except ScriptError as problem:
            return {"ok": False, "error": problem.info}

    async def indicator(self, code: str, candles: list[Candle], symbol: str, timeframe: str, inputs: dict | None = None) -> dict:
        job = {"kind": "indicator", "code": code, "data": candle_arrays(candles), "symbol": symbol, "timeframe": timeframe, "inputs": inputs or {}}
        try:
            result = await asyncio.to_thread(self.indicator_worker.call, job)
        except ScriptError as problem:
            return {"ok": False, "error": problem.info}
        result["times"] = [c.time for c in candles]
        return {"ok": True, **result}

    async def backtest(self, code: str, candles: list[Candle], symbol: str, timeframe: str, starting_balance: float, inputs: dict | None = None, on_progress=None) -> dict:
        market = self.catalog.get(symbol)
        job = {
            "kind": "backtest", "code": code, "data": candle_arrays(candles), "symbol": symbol, "timeframe": timeframe,
            "market": asdict(market), "starting_balance": starting_balance, "inputs": inputs or {},
        }
        try:
            report = await asyncio.to_thread(self.backtest_worker.call, job, BACKTEST_SILENCE_LIMIT, on_progress)
        except ScriptError as problem:
            return {"ok": False, "error": problem.info}
        return {"ok": True, "report": report}

    def warm_up(self) -> None:
        self.indicator_worker.warm_up()

    def close(self) -> None:
        self.indicator_worker.close()
        self.backtest_worker.close()
