"""The demo data provider: made-up but realistic-looking prices that work offline.

It exists so the owner can practice and so the app can be tested without an
internet connection or any account. Prices are calculated from the time
itself, so the same moment always gives the same price: history and live
prices always agree, and tests are repeatable.

How the price is made: random "wiggles" at several sizes (minutes, hours,
days) are added together, which looks much like a real chart.
"""

import asyncio
import math
import time

import numpy as np

from engine.core.models import TIMEFRAMES, Candle, Tick
from engine.data.provider import DataProvider

# Wiggle sizes in seconds and how strong each one is.
_SCALES = [(60, 0.25), (900, 0.6), (3600 * 4, 1.0), (86400 * 3, 1.8), (86400 * 30, 3.0)]
_TICK_INTERVAL = 0.25  # seconds between live demo prices


def _hash_unit(values: np.ndarray, salt: int) -> np.ndarray:
    """Turn whole numbers into repeatable pseudo-random numbers between -1 and 1."""
    x = (values.astype(np.uint64) + np.uint64(salt)) * np.uint64(0x9E3779B97F4A7C15)
    x ^= x >> np.uint64(30)
    x *= np.uint64(0xBF58476D1CE4E5B9)
    x ^= x >> np.uint64(27)
    x *= np.uint64(0x94D049BB133111EB)
    x ^= x >> np.uint64(31)
    return (x >> np.uint64(11)).astype(np.float64) / float(1 << 53) * 2.0 - 1.0


def _salt(name: str) -> int:
    return sum((i + 1) * ord(c) for i, c in enumerate(name)) * 7919


def demo_prices(provider_symbol: str, times: np.ndarray, extra: dict) -> np.ndarray:
    """The demo price at each moment in times (unix seconds)."""
    start_price = float(extra.get("start_price", 100.0))
    volatility = float(extra.get("volatility", 0.0003))
    salt = _salt(extra.get("seed_of", provider_symbol))
    times = np.asarray(times, dtype=np.float64)
    total = np.zeros_like(times)
    for index, (scale, weight) in enumerate(_SCALES):
        position = times / scale
        left = np.floor(position)
        fraction = position - left
        smooth = fraction * fraction * (3 - 2 * fraction)  # eases between the random points
        a = _hash_unit(left.astype(np.int64), salt + index * 1013)
        b = _hash_unit(left.astype(np.int64) + 1, salt + index * 1013)
        total += (a + (b - a) * smooth) * weight * math.sqrt(scale / 60)
    return start_price * np.exp(total * volatility)


def demo_candles(provider_symbol: str, timeframe: str, start: int, end: int, extra: dict, tick_size: float = 0.01) -> list[Candle]:
    seconds = TIMEFRAMES[timeframe]
    first = start // seconds * seconds
    opens = np.arange(first, end + 1, seconds, dtype=np.int64)
    if len(opens) == 0:
        return []
    samples = 12
    offsets = np.linspace(0, seconds, samples + 1)
    grid = opens[:, None] + offsets[None, :]
    prices = demo_prices(provider_symbol, grid.ravel(), extra).reshape(grid.shape)
    volume_noise = (_hash_unit(opens, _salt(provider_symbol) + 77) + 1.2) * (seconds / 60) * 50
    candles = []
    for i, open_time in enumerate(opens):
        row = np.round(prices[i] / tick_size) * tick_size
        candles.append(
            Candle(
                time=int(open_time),
                open=float(row[0]),
                high=float(row.max()),
                low=float(row.min()),
                close=float(row[-1]),
                volume=float(round(volume_noise[i], 2)),
            )
        )
    return candles


class DemoProvider(DataProvider):
    name = "DEMO"

    def __init__(self, markets: dict[str, dict] | None = None, tick_interval: float = _TICK_INTERVAL):
        # provider_symbol -> market extra settings and tick size
        self.markets = markets or {}
        self.tick_interval = tick_interval

    async def fetch_history(self, provider_symbol, timeframe, start, end, extra):
        tick = self.markets.get(provider_symbol, {}).get("tick_size", 0.01)
        return demo_candles(provider_symbol, timeframe, start, end, extra, tick)

    async def stream(self, subscriptions, on_tick, on_candle, on_status):
        on_status(self.name, "connected")
        while True:
            now = time.time()
            for provider_symbol in {s for s, _ in subscriptions()}:
                info = self.markets.get(provider_symbol, {})
                price = float(demo_prices(provider_symbol, np.array([now]), info.get("extra", {}))[0])
                tick_size = info.get("tick_size", 0.01)
                price = round(round(price / tick_size) * tick_size, 10)
                on_tick(Tick(symbol=provider_symbol, time=now, price=price, size=1.0))
            await asyncio.sleep(self.tick_interval)
