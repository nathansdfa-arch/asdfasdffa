"""How a strategy's signals become orders. Shared by backtests and live/paper
trading, so a strategy behaves the same in every mode (bible principle 4).

    buy(quantity, stop, target, limit)   buy that many (a market order, or a limit order if limit is given)
    sell(quantity, stop, target, limit)  sell that many (opens or adds to a short when flat or short)
    close()                              close the whole position
"""

from dataclasses import dataclass

from engine.core.models import OrderType, Side


@dataclass
class PlannedOrder:
    side: Side
    quantity: float
    order_type: OrderType
    price: float | None
    stop_loss: float | None
    take_profit: float | None
    reduce_only: bool


def plan_orders(signal: dict, position_size: float) -> list[PlannedOrder]:
    action = signal.get("action")
    if action == "close":
        if position_size == 0:
            return []
        return [PlannedOrder(Side.SELL if position_size > 0 else Side.BUY, abs(position_size), OrderType.MARKET, None, None, None, True)]
    if action in ("buy", "sell"):
        quantity = float(signal.get("quantity") or 0)
        if quantity <= 0:
            return []
        limit = signal.get("limit")
        return [PlannedOrder(
            Side.BUY if action == "buy" else Side.SELL,
            quantity,
            OrderType.LIMIT if limit is not None else OrderType.MARKET,
            limit,
            signal.get("stop"),
            signal.get("target"),
            False,
        )]
    return []
