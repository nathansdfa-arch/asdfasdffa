"""The DataProvider interface: what every market data source must be able to do.

Bybit, the demo feed, and later Rithmic and MetaTrader 5 are all "plug-ins"
that follow this same shape, so the rest of the app never cares where the
prices come from.
"""

from abc import ABC, abstractmethod
from typing import Awaitable, Callable

from engine.core.models import Candle, Tick

TickHandler = Callable[[Tick], None]
CandleHandler = Callable[[str, str, Candle, bool], None]   # symbol, timeframe, candle, finished?
StatusHandler = Callable[[str, str], None]                  # provider name, "connected" / "disconnected" / message


class ProviderError(Exception):
    """A provider could not do what was asked. The message is plain English."""


class DataProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def fetch_history(self, provider_symbol: str, timeframe: str, start: int, end: int, extra: dict) -> list[Candle]:
        """Candles that opened between start and end (unix seconds, UTC), oldest first."""

    @abstractmethod
    async def stream(
        self,
        subscriptions: Callable[[], set[tuple[str, str]]],
        on_tick: TickHandler,
        on_candle: CandleHandler,
        on_status: StatusHandler,
    ) -> None:
        """Stream live prices until cancelled.

        subscriptions() returns the current set of (provider_symbol, timeframe)
        pairs wanted; the provider checks it regularly so new charts start
        streaming without a restart. Ticks and candles carry the provider's
        own symbol; the data service turns them into app symbols.
        """

    def describe(self) -> dict:
        return {"name": self.name}


Sleep = Callable[[float], Awaitable[None]]
