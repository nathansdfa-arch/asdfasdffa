# Moving averages drawn over the candles, plus RSI in its own panel.

name = "Averages and RSI"
inputs = {"fast": 20, "slow": 50, "rsi_length": 14}


def calculate(data):
    plot("SMA fast", sma(data.close, inputs.fast), color="#9fd3ff")
    plot("SMA slow", sma(data.close, inputs.slow), color="#f2b8d6")
    plot("RSI", rsi(data.close, inputs.rsi_length), pane="rsi", color="#c9b6ff")
    hline(70, pane="rsi", color="#7a7f99")
    hline(30, pane="rsi", color="#7a7f99")
