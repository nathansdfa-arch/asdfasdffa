"""The friendly script library: everything a script can use without importing.

Scripts see these names directly, for example:

    def calculate(data):
        plot("SMA 20", sma(data.close, 20))

All indicator helpers take and return NumPy arrays the same length as the
data, with NaN ("not a number") where there isn't enough history yet.
"""

import math

import numpy as np

# ---------------------------------------------------------------------------
# Data handed to scripts
# ---------------------------------------------------------------------------


class Data:
    """Finished candles, oldest first. data.close[-1] is the most recent close."""

    def __init__(self, time, open, high, low, close, volume, symbol="", timeframe=""):
        self.time = time
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume
        self.symbol = symbol
        self.timeframe = timeframe

    def __len__(self):
        return len(self.close)


class PositionView:
    """What a strategy knows about its position. size > 0 is long, < 0 is short, 0 is flat."""

    def __init__(self, size=0.0, entry_price=0.0):
        self.size = size
        self.entry_price = entry_price

    @property
    def is_flat(self):
        return self.size == 0

    @property
    def is_long(self):
        return self.size > 0

    @property
    def is_short(self):
        return self.size < 0


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------


def _array(values):
    return np.asarray(values, dtype=float)


def sma(values, length):
    """Simple moving average: the average of the last `length` values."""
    values = _array(values)
    out = np.full(len(values), np.nan)
    if length <= 0 or len(values) < length:
        return out
    sums = np.cumsum(np.insert(values, 0, 0.0))
    out[length - 1:] = (sums[length:] - sums[:-length]) / length
    return out


def ema(values, length):
    """Exponential moving average: like sma, but recent values count more."""
    values = _array(values)
    out = np.full(len(values), np.nan)
    if length <= 0 or len(values) < length:
        return out
    alpha = 2 / (length + 1)
    out[length - 1] = values[:length].mean()
    for i in range(length, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def rma(values, length):
    """Wilder's moving average, used by RSI and ATR."""
    values = _array(values)
    out = np.full(len(values), np.nan)
    if length <= 0 or len(values) < length:
        return out
    out[length - 1] = values[:length].mean()
    for i in range(length, len(values)):
        out[i] = (out[i - 1] * (length - 1) + values[i]) / length
    return out


def rsi(values, length=14):
    """Relative Strength Index, from 0 to 100."""
    values = _array(values)
    change = np.diff(values, prepend=np.nan)
    gains = np.where(change > 0, change, 0.0)
    losses = np.where(change < 0, -change, 0.0)
    gains[0] = losses[0] = 0.0
    avg_gain = rma(gains[1:], length)
    avg_loss = rma(losses[1:], length)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
        result = np.where(avg_loss == 0, 100.0, 100 - 100 / (1 + rs))
    return np.concatenate(([np.nan], result))


def true_range(high, low, close):
    high, low, close = _array(high), _array(low), _array(close)
    previous = np.roll(close, 1)
    previous[0] = np.nan
    ranges = np.vstack([high - low, np.abs(high - previous), np.abs(low - previous)])
    out = np.nanmax(ranges, axis=0)
    return out


def atr(high, low, close, length=14):
    """Average True Range: how far price typically moves per candle."""
    return rma(true_range(high, low, close), length)


def stdev(values, length):
    values = _array(values)
    out = np.full(len(values), np.nan)
    for i in range(length - 1, len(values)):
        out[i] = values[i - length + 1:i + 1].std()
    return out


def bollinger(values, length=20, width=2.0):
    """Bollinger bands: returns (middle, upper, lower)."""
    middle = sma(values, length)
    spread = stdev(values, length) * width
    return middle, middle + spread, middle - spread


def highest(values, length):
    values = _array(values)
    out = np.full(len(values), np.nan)
    for i in range(length - 1, len(values)):
        out[i] = values[i - length + 1:i + 1].max()
    return out


def lowest(values, length):
    values = _array(values)
    out = np.full(len(values), np.nan)
    for i in range(length - 1, len(values)):
        out[i] = values[i - length + 1:i + 1].min()
    return out


def macd(values, fast=12, slow=26, signal=9):
    """MACD: returns (macd line, signal line, histogram)."""
    line = ema(values, fast) - ema(values, slow)
    valid = ~np.isnan(line)
    signal_line = np.full(len(line), np.nan)
    if valid.sum() >= signal:
        signal_line[valid] = ema(line[valid], signal)
    return line, signal_line, line - signal_line


def vwap(high, low, close, volume):
    """Volume-weighted average price over all the data given."""
    typical = (_array(high) + _array(low) + _array(close)) / 3
    volume = _array(volume)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.cumsum(typical * volume) / np.cumsum(volume)


def crossover(a, b):
    """True when `a` crossed above `b` on the latest candle."""
    a, b = _series(a), _series(b)
    if len(a) < 2:
        return False
    return bool(a[-2] <= b[-2] and a[-1] > b[-1])


def crossunder(a, b):
    """True when `a` crossed below `b` on the latest candle."""
    a, b = _series(a), _series(b)
    if len(a) < 2:
        return False
    return bool(a[-2] >= b[-2] and a[-1] < b[-1])


def _series(value):
    if np.isscalar(value):
        return np.array([value, value], dtype=float)
    return _array(value)


def last(values, default=math.nan):
    """The most recent value, or `default` if there isn't one."""
    values = _array(values)
    return float(values[-1]) if len(values) else default


# ---------------------------------------------------------------------------
# Outputs: what a script asks the app to draw or do
# ---------------------------------------------------------------------------


class Outputs:
    """Collects plots, signals and messages during one script run."""

    def __init__(self):
        self.plots = []
        self.lines = []
        self.signals = []
        self.messages = []

    def reset_signals(self):
        self.signals = []


_outputs = Outputs()


def plot(name, values, color=None, pane="price", style="line", width=2):
    """Draw a line on the chart. pane="price" draws over the candles; pane="new" (or any
    other name) draws in a separate panel below. style can be "line", "histogram" or "dots"."""
    values = _array(values)
    _outputs.plots.append({"name": str(name), "values": values, "color": color, "pane": pane, "style": style, "width": width})


def hline(value, color=None, pane="price", name=""):
    """A flat line at one value, such as 70 and 30 on an RSI panel."""
    _outputs.lines.append({"value": float(value), "color": color, "pane": pane, "name": name})


def buy(quantity=1, stop=None, target=None, limit=None):
    """Ask to buy. The order still has to pass the risk guard."""
    _outputs.signals.append({"action": "buy", "quantity": float(quantity), "stop": _num(stop), "target": _num(target), "limit": _num(limit)})


def sell(quantity=1, stop=None, target=None, limit=None):
    """Ask to sell (or go short). The order still has to pass the risk guard."""
    _outputs.signals.append({"action": "sell", "quantity": float(quantity), "stop": _num(stop), "target": _num(target), "limit": _num(limit)})


def close():
    """Ask to close the whole position."""
    _outputs.signals.append({"action": "close"})


def alert(message):
    """Show a message to the owner (used by automations and strategies)."""
    _outputs.messages.append(str(message))


def _num(value):
    if value is None:
        return None
    value = float(value)
    return None if math.isnan(value) else value


# Every name a script can use without importing anything.
SCRIPT_NAMES = {
    "np": np, "math": math,
    "sma": sma, "ema": ema, "rma": rma, "rsi": rsi, "atr": atr, "true_range": true_range,
    "stdev": stdev, "bollinger": bollinger, "highest": highest, "lowest": lowest, "macd": macd,
    "vwap": vwap, "crossover": crossover, "crossunder": crossunder, "last": last,
    "plot": plot, "hline": hline, "buy": buy, "sell": sell, "close": close, "alert": alert,
    "nan": math.nan, "isnan": math.isnan,
}
