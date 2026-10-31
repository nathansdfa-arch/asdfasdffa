# Moving average crossover strategy.
# Buys when the fast average crosses above the slow one, sells short when it
# crosses below. Every order carries a stop loss two ATRs away, so it passes
# the risk guard's stop loss rule.

name = "MA crossover"
inputs = {"fast": 10, "slow": 30, "quantity": 1, "atr_stops": 2.0}
lookback = 200


def on_bar(data, position):
    if len(data.close) < inputs.slow + 1:
        return  # not enough history yet

    fast = sma(data.close, inputs.fast)
    slow = sma(data.close, inputs.slow)
    distance = last(atr(data.high, data.low, data.close, 14)) * inputs.atr_stops
    price = data.close[-1]

    if crossover(fast, slow) and not position.is_long:
        close()
        buy(inputs.quantity, stop=price - distance)
    elif crossunder(fast, slow) and not position.is_short:
        close()
        sell(inputs.quantity, stop=price + distance)
