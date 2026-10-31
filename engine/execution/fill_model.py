"""The fill model: how a simulated order turns into a trade.

Both the backtester and the paper broker use these exact rules (bible
section 8), so practice results match backtest results:

  Market orders fill at the next price, plus slippage against you.
  Limit orders fill only once price trades THROUGH the limit (not just touches it),
      at the limit price.
  Stop orders become market orders when price touches them, and then fill
      like a market order, slippage included.
"""

from engine.core.markets import Market
from engine.core.models import Candle, OrderType, Side


def market_fill_price(side: Side, price: float, market: Market) -> float:
    """A market order's fill: the price plus slippage in the direction that costs you."""
    return market.round_price(price + side.sign * market.slippage)


def limit_triggers(side: Side, limit_price: float, price: float) -> bool:
    """A buy limit needs price to trade below it; a sell limit needs price above it."""
    return price < limit_price if side is Side.BUY else price > limit_price


def stop_triggers(side: Side, stop_price: float, price: float) -> bool:
    """A buy stop triggers at or above its price; a sell stop at or below."""
    return price >= stop_price if side is Side.BUY else price <= stop_price


def fill_on_tick(order_type: OrderType, side: Side, order_price: float | None, price: float, market: Market) -> float | None:
    """The fill price if this live price fills the order, otherwise None."""
    if order_type is OrderType.MARKET:
        return market_fill_price(side, price, market)
    if order_type is OrderType.LIMIT and limit_triggers(side, order_price, price):
        return order_price
    if order_type is OrderType.STOP and stop_triggers(side, order_price, price):
        return market_fill_price(side, price, market)
    return None


def fill_on_candle(order_type: OrderType, side: Side, order_price: float | None, candle: Candle, market: Market) -> float | None:
    """The fill price if this candle fills the order, otherwise None (used by backtests).

    A market order fills at the candle's open. A stop that the candle opens
    beyond fills at the open (a gap), otherwise at the stop price; slippage
    is added either way.
    """
    if order_type is OrderType.MARKET:
        return market_fill_price(side, candle.open, market)
    if order_type is OrderType.LIMIT:
        if side is Side.BUY and candle.low < order_price:
            return min(order_price, candle.open)
        if side is Side.SELL and candle.high > order_price:
            return max(order_price, candle.open)
        return None
    if order_type is OrderType.STOP:
        if side is Side.BUY and candle.high >= order_price:
            return market_fill_price(side, max(order_price, candle.open), market)
        if side is Side.SELL and candle.low <= order_price:
            return market_fill_price(side, min(order_price, candle.open), market)
    return None


def apply_fill(quantity: float, average_price: float, signed_quantity: float, price: float, point_value: float) -> tuple[float, float, float]:
    """Update a position with a fill. Returns (new quantity, new average price, realized profit or loss).

    quantity is positive for long and negative for short; signed_quantity is
    positive for a buy and negative for a sell. Used by the paper broker and
    the backtester alike.
    """
    if quantity == 0 or (quantity > 0) == (signed_quantity > 0):
        total = quantity + signed_quantity
        return total, (average_price * quantity + price * signed_quantity) / total, 0.0
    closing = min(abs(signed_quantity), abs(quantity))
    realized = (price - average_price) * closing * (1 if quantity > 0 else -1) * point_value
    remaining = quantity + signed_quantity
    if abs(remaining) < 1e-12:
        return 0.0, 0.0, realized
    if (remaining > 0) == (quantity > 0):
        return remaining, average_price, realized
    return remaining, price, realized       # flipped: the rest opens at this price
