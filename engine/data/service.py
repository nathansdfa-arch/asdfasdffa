"""The market data service: the one place the rest of the app gets prices from.

It knows every provider, fills the cache, builds the candle that is forming
right now from live ticks, and watches each feed's health:

  ok    prices are arriving
  stale no new price for a while during market hours (yellow banner)
  down  the provider is disconnected (red banner; the risk guard blocks new orders)
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field

from engine.core.bus import MessageBus
from engine.core.markets import MarketCatalog, floor_time
from engine.core.models import Candle, Tick, timeframe_seconds
from engine.data.cache import CandleCache, find_gaps
from engine.data.provider import DataProvider, ProviderError

log = logging.getLogger(__name__)

STALE_AFTER_SECONDS = 5


@dataclass
class FeedState:
    last_price: float | None = None
    last_tick_at: float | None = None      # engine clock time when the last tick arrived
    status: str = "waiting"                # waiting, ok, stale, down
    forming: dict = field(default_factory=dict)   # timeframe -> Candle being built now


class MarketDataService:
    def __init__(self, catalog: MarketCatalog, cache: CandleCache, providers: dict[str, DataProvider], bus: MessageBus, clock=time.time):
        self.catalog = catalog
        self.cache = cache
        self.providers = providers
        self.bus = bus
        self.clock = clock
        self.feeds: dict[str, FeedState] = {}
        self.provider_status: dict[str, str] = {name: "idle" for name in providers}
        # app symbol -> set of timeframes that screens or strategies want live
        self.live_wanted: dict[str, set[str]] = {}
        self._tasks: list[asyncio.Task] = []
        self.stale_after = STALE_AFTER_SECONDS

    # ---- History ----------------------------------------------------------

    async def history(self, symbol: str, timeframe: str, start: int, end: int) -> dict:
        """Candles for a chart or backtest, from cache where possible.

        Returns {"candles", "gaps", "fetched", "warning"}.
        """
        market = self.catalog.get(symbol)
        seconds = timeframe_seconds(timeframe)
        provider = self.providers[market.provider]
        now = self.clock()
        last_finished = floor_time(now, seconds) - seconds   # newest candle that has closed
        end = min(end, floor_time(now, seconds))
        start = floor_time(start, seconds)
        warning = None
        fetched = 0

        to_fetch = []
        coverage = self.cache.coverage(symbol, timeframe)
        if coverage is None:
            to_fetch.append((start, last_finished))
        else:
            covered_start, covered_end = coverage
            if start < covered_start:
                to_fetch.append((start, covered_start - seconds))
            if last_finished > covered_end:
                to_fetch.append((covered_end + seconds, last_finished))

        new_start = coverage[0] if coverage else None
        new_end = coverage[1] if coverage else None
        for fetch_start, fetch_end in to_fetch:
            if fetch_end < fetch_start:
                continue
            try:
                candles = await provider.fetch_history(market.provider_symbol, timeframe, fetch_start, fetch_end, {**market.extra, "tick_size": market.tick_size})
            except ProviderError as problem:
                warning = str(problem) + " Showing what is saved on this computer."
                log.warning("History fetch failed for %s %s: %s", symbol, timeframe, problem)
                break
            finished = [c for c in candles if c.time <= last_finished]
            self.cache.write(symbol, timeframe, finished)
            fetched += len(finished)
            new_start = fetch_start if new_start is None else min(new_start, fetch_start)
            new_end = fetch_end if new_end is None else max(new_end, fetch_end)
        if new_start is not None and new_end is not None:
            self.cache.set_coverage(symbol, timeframe, new_start, new_end)

        candles = self.cache.read(symbol, timeframe, start, end)
        forming = self.feeds.get(symbol, FeedState()).forming.get(timeframe)
        if forming and (not candles or forming.time > candles[-1].time):
            candles.append(forming)
        return {
            "candles": candles,
            "gaps": find_gaps(candles, seconds, market.is_open),
            "fetched": fetched,
            "warning": warning,
        }

    # ---- Live -------------------------------------------------------------

    def want_live(self, symbol: str, timeframe: str) -> None:
        self.catalog.get(symbol)  # raises for unknown symbols
        self.live_wanted.setdefault(symbol, set()).add(timeframe)
        self.feeds.setdefault(symbol, FeedState())

    def last_price(self, symbol: str) -> float | None:
        feed = self.feeds.get(symbol)
        return feed.last_price if feed else None

    def feed_status(self, symbol: str) -> str:
        feed = self.feeds.get(symbol)
        return feed.status if feed else "waiting"

    def seconds_since_tick(self, symbol: str) -> float | None:
        feed = self.feeds.get(symbol)
        if not feed or feed.last_tick_at is None:
            return None
        return self.clock() - feed.last_tick_at

    def _subscriptions_for(self, provider_name: str):
        def wanted() -> set[tuple[str, str]]:
            pairs = set()
            for symbol, timeframes in self.live_wanted.items():
                market = self.catalog.markets.get(symbol)
                if market and market.provider == provider_name:
                    for tf in timeframes or {"1m"}:
                        pairs.add((market.provider_symbol, tf))
            return pairs
        return wanted

    def _app_symbol(self, provider_name: str, provider_symbol: str) -> str:
        return f"{provider_name}:{provider_symbol}"

    def on_tick(self, provider_name: str, tick: Tick) -> None:
        """A new live price. Updates the forming candles and tells everyone."""
        symbol = self._app_symbol(provider_name, tick.symbol)
        feed = self.feeds.setdefault(symbol, FeedState())
        feed.last_price = tick.price
        feed.last_tick_at = self.clock()
        if feed.status != "ok":
            self._set_status(symbol, "ok")
        for timeframe in self.live_wanted.get(symbol, set()) | {"1m"}:
            seconds = timeframe_seconds(timeframe)
            open_time = floor_time(tick.time, seconds)
            current = feed.forming.get(timeframe)
            if current is None or open_time > current.time:
                if current is not None:
                    self._finish_candle(symbol, timeframe, current)
                current = Candle(open_time, tick.price, tick.price, tick.price, tick.price, tick.size)
            elif open_time == current.time:
                current = Candle(
                    current.time, current.open, max(current.high, tick.price), min(current.low, tick.price),
                    tick.price, current.volume + tick.size,
                )
            else:
                continue  # a late tick for an older candle; ignore it
            feed.forming[timeframe] = current
            self.bus.publish("candle", {"symbol": symbol, "timeframe": timeframe, "candle": current.to_dict(), "finished": False})
        self.bus.publish("tick", {"symbol": symbol, "price": tick.price, "time": tick.time})

    def on_provider_candle(self, provider_name: str, provider_symbol: str, timeframe: str, candle: Candle, finished: bool) -> None:
        """A candle reported by the provider itself. Finished ones are the official record."""
        symbol = self._app_symbol(provider_name, provider_symbol)
        if finished:
            self._finish_candle(symbol, timeframe, candle)
            feed = self.feeds.setdefault(symbol, FeedState())
            current = feed.forming.get(timeframe)
            if current is not None and current.time <= candle.time:
                del feed.forming[timeframe]

    def _finish_candle(self, symbol: str, timeframe: str, candle: Candle) -> None:
        self.cache.write(symbol, timeframe, [candle])
        coverage = self.cache.coverage(symbol, timeframe)
        if coverage and coverage[1] + timeframe_seconds(timeframe) >= candle.time:
            self.cache.set_coverage(symbol, timeframe, coverage[0], max(coverage[1], candle.time))
        self.bus.publish("candle", {"symbol": symbol, "timeframe": timeframe, "candle": candle.to_dict(), "finished": True})

    def on_status(self, provider_name: str, status: str) -> None:
        self.provider_status[provider_name] = status
        log.info("Provider %s: %s", provider_name, status)
        if status != "connected":
            for symbol in list(self.feeds):
                if symbol.startswith(provider_name + ":"):
                    self._set_status(symbol, "down")
        self.bus.publish("provider", {"provider": provider_name, "status": status})

    def _set_status(self, symbol: str, status: str) -> None:
        feed = self.feeds.setdefault(symbol, FeedState())
        if feed.status == status:
            return
        feed.status = status
        log.info("Feed %s is now %s", symbol, status)
        self.bus.publish("feed", {"symbol": symbol, "status": status})

    def check_health(self) -> None:
        """Mark feeds stale when prices stop during market hours. Called every second."""
        now = self.clock()
        for symbol, feed in self.feeds.items():
            market = self.catalog.markets.get(symbol)
            if market is None or feed.status in ("down", "waiting"):
                continue
            quiet_for = now - (feed.last_tick_at or now)
            if quiet_for >= self.stale_after and market.is_open(now):
                self._set_status(symbol, "stale")

    async def start(self) -> None:
        """Start streaming from every provider and the health watchdog."""
        for name, provider in self.providers.items():
            task = asyncio.create_task(
                provider.stream(
                    self._subscriptions_for(name),
                    lambda tick, n=name: self.on_tick(n, tick),
                    lambda sym, tf, candle, done, n=name: self.on_provider_candle(n, sym, tf, candle, done),
                    self.on_status,
                ),
                name=f"stream-{name}",
            )
            self._tasks.append(task)
        self._tasks.append(asyncio.create_task(self._watchdog(), name="feed-watchdog"))

    async def _watchdog(self) -> None:
        while True:
            self.check_health()
            await asyncio.sleep(1)

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
