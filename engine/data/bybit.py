"""Bybit market data: free public history and live prices. No account needed.

History comes from Bybit's public "kline" web address, up to 1000 candles
per request. Live prices come from Bybit's public WebSocket stream, using
every trade ("publicTrade") for ticks and "kline" messages to confirm each
finished candle.

Bybit documentation: https://bybit-exchange.github.io/docs/v5/intro
"""

import asyncio
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from engine.core.models import TIMEFRAMES, Candle, Tick
from engine.data.provider import DataProvider, ProviderError

log = logging.getLogger(__name__)

REST_URL = os.environ.get("BYBIT_REST_URL", "https://api.bybit.com")
WS_URL = os.environ.get("BYBIT_WS_URL", "wss://stream.bybit.com/v5/public/{category}")

# The app's timeframe names and Bybit's names for them.
INTERVALS = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D"}
PAGE_SIZE = 1000
PING_EVERY = 20       # Bybit closes quiet connections, so say hello every 20 seconds
RECONNECT_DELAYS = [1, 2, 5, 10, 30]


def parse_kline_rows(rows: list[list[str]]) -> list[Candle]:
    """Turn Bybit's kline rows (newest first, all text) into candles, oldest first."""
    candles = [
        Candle(
            time=int(row[0]) // 1000,
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
        )
        for row in rows
    ]
    candles.sort(key=lambda c: c.time)
    return candles


class BybitProvider(DataProvider):
    name = "BYBIT"

    def __init__(self, http_get=None):
        # http_get(url) -> parsed JSON. Tests pass a fake one.
        self._http_get = http_get or self._default_http_get

    @staticmethod
    def _default_http_get(url: str) -> dict:
        request = urllib.request.Request(url, headers={"User-Agent": "TradingApp/0.1"})
        with urllib.request.urlopen(request, timeout=10) as reply:
            return json.load(reply)

    async def fetch_history(self, provider_symbol, timeframe, start, end, extra):
        if timeframe not in INTERVALS:
            raise ProviderError(f"Bybit does not offer the {timeframe} timeframe.")
        seconds = TIMEFRAMES[timeframe]
        category = extra.get("category", "linear")
        collected: dict[int, Candle] = {}
        cursor_end = end
        # Walk backwards from the newest candle, one page at a time.
        while cursor_end >= start:
            query = urllib.parse.urlencode({
                "category": category,
                "symbol": provider_symbol,
                "interval": INTERVALS[timeframe],
                "start": start * 1000,
                "end": cursor_end * 1000,
                "limit": PAGE_SIZE,
            })
            try:
                data = await asyncio.to_thread(self._http_get, f"{REST_URL}/v5/market/kline?{query}")
            except (urllib.error.URLError, OSError, ValueError) as problem:
                raise ProviderError(f"Could not reach Bybit for price history ({problem}).") from problem
            if data.get("retCode") != 0:
                raise ProviderError(f"Bybit refused the history request: {data.get('retMsg', 'no reason given')}.")
            page = parse_kline_rows(data.get("result", {}).get("list", []))
            if not page:
                break
            for candle in page:
                if start <= candle.time <= end:
                    collected[candle.time] = candle
            oldest = page[0].time
            if oldest <= start or len(page) < PAGE_SIZE:
                break
            cursor_end = oldest - seconds
        return [collected[t] for t in sorted(collected)]

    async def stream(self, subscriptions, on_tick, on_candle, on_status):
        """Keep a live connection open, reconnecting with growing pauses if it drops."""
        import websockets  # imported here so the rest of the app works without it

        attempt = 0
        while True:
            wanted = subscriptions()
            if not wanted:
                await asyncio.sleep(1)
                continue
            # All symbols in config are "linear" (USDT perpetuals) for now.
            url = WS_URL.format(category="linear")
            try:
                async with websockets.connect(url, ping_interval=None, open_timeout=10) as socket:
                    subscribed = set()
                    on_status(self.name, "connected")
                    attempt = 0
                    last_ping = time.monotonic()
                    while True:
                        wanted = subscriptions()
                        new_topics = self._topics(wanted) - subscribed
                        if new_topics:
                            await socket.send(json.dumps({"op": "subscribe", "args": sorted(new_topics)}))
                            subscribed |= new_topics
                        if time.monotonic() - last_ping > PING_EVERY:
                            await socket.send(json.dumps({"op": "ping"}))
                            last_ping = time.monotonic()
                        try:
                            raw = await asyncio.wait_for(socket.recv(), timeout=1)
                        except asyncio.TimeoutError:
                            continue
                        self.handle_message(json.loads(raw), on_tick, on_candle)
            except asyncio.CancelledError:
                raise
            except Exception as problem:  # network trouble of any kind
                on_status(self.name, f"disconnected: {problem}")
                delay = RECONNECT_DELAYS[min(attempt, len(RECONNECT_DELAYS) - 1)]
                attempt += 1
                log.warning("Bybit live stream dropped (%s). Reconnecting in %ds.", problem, delay)
                await asyncio.sleep(delay)

    @staticmethod
    def _topics(wanted: set[tuple[str, str]]) -> set[str]:
        topics = set()
        for symbol, timeframe in wanted:
            topics.add(f"publicTrade.{symbol}")
            if timeframe in INTERVALS:
                topics.add(f"kline.{INTERVALS[timeframe]}.{symbol}")
        return topics

    @staticmethod
    def handle_message(message: dict, on_tick, on_candle) -> None:
        """Turn one Bybit stream message into ticks or candles."""
        topic = message.get("topic", "")
        if topic.startswith("publicTrade."):
            for trade in message.get("data", []):
                on_tick(Tick(symbol=trade["s"], time=int(trade["T"]) / 1000, price=float(trade["p"]), size=float(trade["v"])))
        elif topic.startswith("kline."):
            _, interval, symbol = topic.split(".", 2)
            timeframe = next((tf for tf, code in INTERVALS.items() if code == interval), None)
            if timeframe is None:
                return
            for k in message.get("data", []):
                candle = Candle(
                    time=int(k["start"]) // 1000,
                    open=float(k["open"]), high=float(k["high"]), low=float(k["low"]),
                    close=float(k["close"]), volume=float(k["volume"]),
                )
                on_candle(symbol, timeframe, candle, bool(k.get("confirm")))
