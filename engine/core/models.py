"""The shared shapes of data that every part of the app passes around.

Keeping one definition of a candle, an order, a position and so on means
every market and every broker looks the same to the rest of the app.
All times are whole seconds since 1 January 1970, in UTC ("unix time").
"""

from dataclasses import asdict, dataclass, field
from enum import Enum

# Chart timeframes and how many seconds each candle covers.
TIMEFRAMES = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


def timeframe_seconds(timeframe: str) -> int:
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"Unknown timeframe '{timeframe}'. Use one of: {', '.join(TIMEFRAMES)}.")
    return TIMEFRAMES[timeframe]


@dataclass(frozen=True)
class Candle:
    time: int        # when the candle opened, unix seconds UTC
    open: float
    high: float
    low: float
    close: float
    volume: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Tick:
    symbol: str
    time: float      # unix seconds UTC, with fractions
    price: float
    size: float = 0.0


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"

    @property
    def sign(self) -> int:
        """+1 for buy, -1 for sell. Handy for profit maths."""
        return 1 if self is Side.BUY else -1

    def opposite(self) -> "Side":
        return Side.SELL if self is Side.BUY else Side.BUY


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class OrderStatus(str, Enum):
    WORKING = "working"      # waiting at the broker to be filled
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class OrderRequest:
    """What a script, button or automation asks for. It must pass the risk guard before going anywhere."""

    account_id: str
    symbol: str
    side: Side
    quantity: float
    order_type: OrderType = OrderType.MARKET
    price: float | None = None          # limit or stop price
    stop_loss: float | None = None      # protective stop, sent to the broker as a real order
    take_profit: float | None = None
    source: str = "manual"              # "manual", "chart", "script:<name>", "automation:<name>"
    reduce_only: bool = False           # True when the order can only shrink a position
    client_tag: str = ""                # free text for the owner's own reference


@dataclass
class Order:
    id: str
    account_id: str
    symbol: str
    side: Side
    quantity: float
    order_type: OrderType
    price: float | None
    status: OrderStatus
    created_at: float
    parent_id: str | None = None        # set on stop loss / take profit orders attached to a position
    role: str = "entry"                 # "entry", "stop_loss", "take_profit", "close"
    source: str = "manual"
    filled_price: float | None = None
    filled_at: float | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["side"] = self.side.value
        data["order_type"] = self.order_type.value
        data["status"] = self.status.value
        return data


@dataclass
class Fill:
    order_id: str
    account_id: str
    symbol: str
    side: Side
    quantity: float
    price: float
    time: float
    fee: float = 0.0


@dataclass
class Position:
    account_id: str
    symbol: str
    quantity: float = 0.0               # positive = long, negative = short
    average_price: float = 0.0
    realized_pnl: float = 0.0

    @property
    def is_flat(self) -> bool:
        return abs(self.quantity) < 1e-12

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AccountSnapshot:
    """An account's money at a moment in time, as the guard and the status strip see it."""

    account_id: str
    balance: float                      # closed balance after fees
    open_pnl: float = 0.0
    fees_today: float = 0.0
    realized_today: float = 0.0
    extra: dict = field(default_factory=dict)

    @property
    def equity(self) -> float:
        return self.balance + self.open_pnl
