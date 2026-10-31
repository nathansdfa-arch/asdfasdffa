# Simple volume indicator.
# Draws volume as bars in its own panel, with a moving average line on top,
# so unusually busy candles stand out.

name = "Volume"
inputs = {"average": 20}


def calculate(data):
    plot("Volume", data.volume, pane="volume", style="histogram", color="#8a93b8")
    plot("Average volume", sma(data.volume, inputs.average), pane="volume", color="#e6c97a")
