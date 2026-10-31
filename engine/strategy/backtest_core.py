"""The backtest loop. Replays history one candle at a time through a strategy.

Rules that keep backtests honest:
  - the strategy only sees finished candles up to "now" (no peeking ahead)
  - signals from a candle are acted on from the NEXT candle, using the shared fill model
  - protective stops are checked before targets inside a candle (assume the worse)
  - fees and slippage come from the market's settings in config/markets.json
"""

import math

import numpy as np

from engine.core.markets import Market
from engine.core.models import Candle, OrderType, Side
from engine.execution import fill_model
from engine.strategy.signals import plan_orders

HEARTBEAT_EVERY = 500


def run_backtest(on_bar, arrays: dict, market: Market, starting_balance: float, lookback: int, heartbeat=None) -> dict:
    """on_bar(window_arrays, position_size, entry_price) -> list of signals."""
    times, opens, highs, lows, closes, volumes = (np.asarray(arrays[k]) for k in ("time", "open", "high", "low", "close", "volume"))
    count = len(closes)
    qty = 0.0
    avg = 0.0
    balance = starting_balance
    fees_total = 0.0
    stop = target = None
    pending: list[dict] = []
    trades: list[dict] = []
    open_trade: dict | None = None
    equity_times: list[int] = []
    equity_values: list[float] = []
    signal_log: list[dict] = []

    def fill(side: Side, quantity: float, price: float, time: int, reduce_only: bool, new_stop, new_target, reason: str):
        nonlocal qty, avg, balance, fees_total, stop, target, open_trade
        if reduce_only:
            if qty == 0 or (qty > 0) == (side is Side.BUY):
                return
            quantity = min(quantity, abs(qty))
        fee = market.fee(quantity, price)
        before = qty
        qty, avg, realized = fill_model.apply_fill(qty, avg, quantity * side.sign, price, market.point_value)
        balance += realized - fee
        fees_total += fee
        if open_trade is not None:
            open_trade["pnl"] += realized - fee
            open_trade["fees"] += fee
        if before == 0 or (qty != 0 and (qty > 0) != (before > 0)):
            # A new trade starts (from flat, or after a flip).
            if open_trade is not None and before != 0:
                _close_trade(open_trade, price, time, reason)
                trades.append(open_trade)
            open_trade = {"side": "long" if qty > 0 else "short", "entry_time": time, "entry_price": price,
                          "quantity": abs(qty), "pnl": -fee if before == 0 else 0.0, "fees": fee if before == 0 else 0.0}
        elif qty == 0 and open_trade is not None:
            _close_trade(open_trade, price, time, reason)
            trades.append(open_trade)
            open_trade = None
        if qty == 0:
            stop = target = None
        else:
            if new_stop is not None:
                stop = new_stop
            if new_target is not None:
                target = new_target

    for i in range(count):
        candle = Candle(int(times[i]), float(opens[i]), float(highs[i]), float(lows[i]), float(closes[i]), float(volumes[i]))

        # 1. Orders from earlier signals.
        for order in list(pending):
            price = fill_model.fill_on_candle(order["type"], order["side"], order["price"], candle, market)
            if price is not None:
                pending.remove(order)
                fill(order["side"], order["quantity"], price, candle.time, order["reduce_only"], order["stop"], order["target"], "signal")

        # 2. Protective stop first, then target.
        if qty != 0 and stop is not None:
            exit_side = Side.SELL if qty > 0 else Side.BUY
            price = fill_model.fill_on_candle(OrderType.STOP, exit_side, stop, candle, market)
            if price is not None:
                fill(exit_side, abs(qty), price, candle.time, True, None, None, "stop loss")
        if qty != 0 and target is not None:
            exit_side = Side.SELL if qty > 0 else Side.BUY
            price = fill_model.fill_on_candle(OrderType.LIMIT, exit_side, target, candle, market)
            if price is not None:
                fill(exit_side, abs(qty), price, candle.time, True, None, None, "target")

        # 3. Equity at the close of this candle.
        equity_times.append(candle.time)
        equity_values.append(balance + (candle.close - avg) * qty * market.point_value)

        # 4. The strategy sees candles up to and including this finished one.
        start = max(0, i + 1 - lookback)
        window = {k: np.asarray(arrays[k])[start:i + 1] for k in ("time", "open", "high", "low", "close", "volume")}
        signals = on_bar(window, qty, avg)
        if signals:
            signal_log.append({"time": candle.time, "signals": signals})
        for signal in signals:
            if signal.get("action") == "close":
                pending = [o for o in pending if o["reduce_only"]]
            for planned in plan_orders(signal, qty):
                pending.append({
                    "side": planned.side, "quantity": planned.quantity, "type": planned.order_type, "price": planned.price,
                    "stop": planned.stop_loss, "target": planned.take_profit, "reduce_only": planned.reduce_only,
                })

        if heartbeat and i % HEARTBEAT_EVERY == 0:
            heartbeat(i / max(count, 1))

    if open_trade is not None and count:
        open_trade["open"] = True
        open_trade["exit_price"] = float(closes[-1])
        open_trade["exit_time"] = int(times[-1])
        open_trade["pnl"] += (float(closes[-1]) - avg) * qty * market.point_value
        open_trade["exit_reason"] = "still open at the end"
        trades.append(open_trade)

    return build_report(trades, equity_times, equity_values, starting_balance, fees_total, signal_log)


def _close_trade(trade: dict, price: float, time: int, reason: str) -> None:
    trade["exit_price"] = price
    trade["exit_time"] = time
    trade["exit_reason"] = reason


def build_report(trades, equity_times, equity_values, starting_balance, fees_total, signal_log) -> dict:
    """The numbers the bible asks for: net profit, win rate, max drawdown, average win and loss, equity curve."""
    closed = [t for t in trades if not t.get("open")]
    wins = [t["pnl"] for t in closed if t["pnl"] > 0]
    losses = [t["pnl"] for t in closed if t["pnl"] <= 0]
    equity = np.asarray(equity_values, dtype=float) if equity_values else np.asarray([starting_balance])
    peaks = np.maximum.accumulate(equity)
    drawdowns = peaks - equity
    worst = int(np.argmax(drawdowns)) if len(drawdowns) else 0
    max_dd = float(drawdowns[worst]) if len(drawdowns) else 0.0
    max_dd_pct = float(max_dd / peaks[worst] * 100) if len(drawdowns) and peaks[worst] else 0.0
    gross_profit = float(sum(wins))
    gross_loss = float(-sum(losses))
    final = float(equity[-1])

    # Keep the equity curve to at most 2,000 points so the screen stays quick.
    step = max(1, len(equity_values) // 2000)
    curve = [{"time": int(t), "value": round(float(v), 2)} for t, v in zip(equity_times[::step], equity_values[::step])]
    if equity_values and (len(equity_values) - 1) % step:
        curve.append({"time": int(equity_times[-1]), "value": round(float(equity_values[-1]), 2)})

    def clean(value):
        return None if value is None or (isinstance(value, float) and math.isnan(value)) else round(value, 2)

    return {
        "starting_balance": starting_balance,
        "final_equity": round(final, 2),
        "net_profit": round(final - starting_balance, 2),
        "total_trades": len(closed),
        "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else 0.0,
        "average_win": clean(gross_profit / len(wins)) if wins else 0.0,
        "average_loss": clean(-gross_loss / len(losses)) if losses else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss else None,
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_percent": round(max_dd_pct, 2),
        "fees_paid": round(fees_total, 2),
        "equity_curve": curve,
        "trades": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in t.items()} for t in trades[-1000:]],
        "signals": signal_log,
    }
