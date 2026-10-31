"""Markets: the facts about each tradable symbol.

Facts live in config/markets.json so the owner can add symbols or change
fees and slippage without touching code. Every symbol is written as
"PROVIDER:SYMBOL", for example "BYBIT:BTCUSDT" or "DEMO:ES".
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


@dataclass(frozen=True)
class Market:
    symbol: str                 # "BYBIT:BTCUSDT"
    name: str                   # shown on screen
    market_type: str            # crypto, futures, forex, cfd, indices, stocks
    provider: str               # "BYBIT" or "DEMO"
    provider_symbol: str        # what the provider calls it, e.g. "BTCUSDT"
    tick_size: float            # smallest price step
    point_value: float          # money made per 1.0 price move per 1 unit of quantity
    fee_per_unit: float         # commission per unit per side, in account currency
    fee_rate: float             # commission as a fraction of trade value per side (crypto style)
    slippage_ticks: float       # assumed slippage on market orders, in ticks
    min_quantity: float
    quantity_step: float
    sessions: str = "24/7"      # "24/7" or a weekly schedule, see is_open()
    timezone: str = "UTC"       # the exchange's own time zone for sessions
    extra: dict = field(default_factory=dict)

    @property
    def slippage(self) -> float:
        return self.slippage_ticks * self.tick_size

    def fee(self, quantity: float, price: float) -> float:
        """Commission for one side of a trade."""
        return abs(quantity) * self.fee_per_unit + abs(quantity) * price * self.point_value * self.fee_rate

    def round_price(self, price: float) -> float:
        return round(round(price / self.tick_size) * self.tick_size, 10)

    def is_open(self, unix_time: float) -> bool:
        """Whether the market trades at this moment.

        sessions is "24/7", or "Sun 18:00-Fri 17:00" meaning open from Sunday
        18:00 to Friday 17:00 in the market's own time zone, with an optional
        daily break such as "daily break 17:00-18:00".
        """
        if self.sessions == "24/7":
            return True
        local = datetime.fromtimestamp(unix_time, tz=timezone.utc).astimezone(ZoneInfo(self.timezone))
        week_minute = local.weekday() * 1440 + local.hour * 60 + local.minute  # Monday 00:00 = 0
        spec = self.sessions.split(";")
        open_part = spec[0].strip()
        start, end = (_week_minute(p) for p in open_part.split("-"))
        inside = start <= week_minute < end if start < end else (week_minute >= start or week_minute < end)
        if not inside:
            return False
        for extra in spec[1:]:
            extra = extra.strip()
            if extra.startswith("daily break"):
                b_start, b_end = (_day_minute(p) for p in extra.replace("daily break", "").strip().split("-"))
                day_minute = local.hour * 60 + local.minute
                if b_start <= day_minute < b_end:
                    return False
        return True

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol, "name": self.name, "market_type": self.market_type,
            "provider": self.provider, "tick_size": self.tick_size, "point_value": self.point_value,
            "min_quantity": self.min_quantity, "quantity_step": self.quantity_step,
            "sessions": self.sessions, "timezone": self.timezone,
        }


_DAYS = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}


def _day_minute(text: str) -> int:
    hours, minutes = text.strip().split(":")
    return int(hours) * 60 + int(minutes)


def _week_minute(text: str) -> int:
    day, clock = text.strip().split(" ")
    return _DAYS[day] * 1440 + _day_minute(clock)


class MarketCatalog:
    """All known markets, loaded from config/markets.json."""

    def __init__(self, path: Path | None = None):
        path = path or CONFIG_DIR / "markets.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.markets: dict[str, Market] = {}
        for item in raw["markets"]:
            market = Market(**item)
            self.markets[market.symbol] = market
        self.watchlists: dict[str, list[str]] = raw.get("watchlists", {})

    def get(self, symbol: str) -> Market:
        if symbol not in self.markets:
            raise KeyError(f"Unknown symbol '{symbol}'. Add it to config/markets.json first.")
        return self.markets[symbol]

    def all(self) -> list[Market]:
        return list(self.markets.values())


def floor_time(unix_time: float, seconds: int) -> int:
    """The start of the candle that contains this moment."""
    return int(unix_time // seconds * seconds)


def utc_midnight(unix_time: float) -> datetime:
    day = datetime.fromtimestamp(unix_time, tz=timezone.utc)
    return day.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(0)
