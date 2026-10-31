# RSI strategy.
# Buys when RSI climbs back above the oversold level, and closes when it
# reaches the overbought level. Uses a stop loss and a target.

name = "RSI strategy"
inputs = {"length": 14, "oversold": 30, "overbought": 70, "quantity": 1, "stop_atr": 1.5, "target_atr": 3.0}
lookback = 200


def on_bar(data, position):
    if len(data.close) < inputs.length + 2:
        return

    strength = rsi(data.close, inputs.length)
    range_size = last(atr(data.high, data.low, data.close, 14))
    price = data.close[-1]

    if position.is_flat and crossover(strength, inputs.oversold):
        buy(inputs.quantity, stop=price - range_size * inputs.stop_atr, target=price + range_size * inputs.target_atr)
    elif position.is_long and last(strength) >= inputs.overbought:
        close()
