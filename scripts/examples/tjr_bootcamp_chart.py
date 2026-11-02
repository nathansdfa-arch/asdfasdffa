# TJR Boot Camp chart view.
#
# Draws what the TJR Boot Camp strategy looks at, so you can check it by eye:
#   - the latest 5 minute swing high and swing low (two-candle rule) [D6]
#   - the 50% line of the current 1 hour move (equilibrium) [D26]
#   - a "bias" panel: daily trend (bars) and 4 hour trend (line), +1 up, -1 down [D34]
#   - a "window" panel that lights up from 9:30 to 11:00 New York time [D29]
# Use it on a 5 minute chart next to the TJR Boot Camp strategy.
# (Scripts can't share code, so the structure rules below are a copy of the
# strategy's. Change both if you change one.)

name = "TJR Boot Camp chart view"
inputs = {"start_time": "09:30", "end_time": "11:00"}

import datetime

# ---------------------------------------------------------------------------
# New York time without a time zone database
# ---------------------------------------------------------------------------

_dst_cache = {}


def _dst_bounds(year):
    """US daylight saving: second Sunday of March 2:00 to first Sunday of November 2:00, in UTC seconds."""
    if year not in _dst_cache:
        march = datetime.datetime(year, 3, 8, tzinfo=datetime.timezone.utc)
        march += datetime.timedelta(days=(6 - march.weekday()) % 7)
        november = datetime.datetime(year, 11, 1, tzinfo=datetime.timezone.utc)
        november += datetime.timedelta(days=(6 - november.weekday()) % 7)
        _dst_cache[year] = (march.timestamp() + 7 * 3600, november.timestamp() + 6 * 3600)
    return _dst_cache[year]


def ny_time(t):
    """Unix seconds -> New York wall clock as seconds (so // 86400 gives the New York day)."""
    year = datetime.datetime.fromtimestamp(t, datetime.timezone.utc).year
    start, end = _dst_bounds(year)
    return t + (-4 * 3600 if start <= t < end else -5 * 3600)


def _minutes(text):
    hours, minutes = str(text).split(":")
    return int(hours) * 60 + int(minutes)


# ---------------------------------------------------------------------------
# Market structure on one timeframe [D2, D4, D6, D14-D18, D20-D24]
# ---------------------------------------------------------------------------


class Structure:
    def __init__(self, seconds, base_seconds):
        self.seconds = seconds
        self.base_seconds = base_seconds
        self.current = None          # the candle still being built
        self.bars = []               # finished candles: [time, open, high, low, close, direction]
        self.swing_high = None       # (level, time) of the most recent swing high [D6]
        self.swing_low = None
        self.highs = []              # recent swing high levels, for liquidity targets [D12]
        self.lows = []
        self.trend = 0               # 1 up, -1 down, 0 not known yet
        self.fvgs = []               # active gaps: [direction, bottom, top, time] [D16]
        self.ob = None               # last order block: [direction, bottom, top, time] [D20, D24]
        self.leg_low = None          # the move since the last break, for the 50% line [D26]
        self.leg_high = None
        self.last_bos = 0            # +1 or -1 when the newest finished candle broke structure

    def _bucket(self, t):
        local = ny_time(t)
        return local // self.seconds

    def add(self, t, o, h, l, c):
        """Feed one base candle. Returns True when a candle on this timeframe finished."""
        self.last_bos = 0
        if self.seconds == self.base_seconds:
            self._finish([t, o, h, l, c])
            return True
        bucket = self._bucket(t)
        finished = False
        if self.current is not None and bucket != self.current[5]:
            self._finish(self.current[:5])
            self.current = None
            finished = True
        if self.current is None:
            self.current = [t, o, h, l, c, bucket]
        else:
            self.current[2] = max(self.current[2], h)
            self.current[3] = min(self.current[3], l)
            self.current[4] = c
        # Finish as soon as the last base candle of the bucket is in, so nothing waits a bar.
        if self._bucket(t + self.base_seconds) != bucket:
            self._finish(self.current[:5])
            self.current = None
            finished = True
        return finished

    def _finish(self, candle):
        t, o, h, l, c = candle
        if c > o:
            direction = 1
        elif c < o:
            direction = -1
        else:  # a doji keeps the previous candle's direction (TJR doesn't say) [ASSUMPTION]
            direction = self.bars[-1][5] if self.bars else 0
        bar = [t, o, h, l, c, direction]

        # 1. Break of structure: a candle BODY closing past the latest swing [D6].
        #    In an uptrend only the latest low matters, in a downtrend only the latest high.
        if self.trend == 1 and self.swing_low is not None and c < self.swing_low[0]:
            self._break(-1, bar)
        elif self.trend == -1 and self.swing_high is not None and c > self.swing_high[0]:
            self._break(1, bar)
        elif self.trend == 0:
            if self.swing_high is not None and c > self.swing_high[0]:
                self._break(1, bar)
            elif self.swing_low is not None and c < self.swing_low[0]:
                self._break(-1, bar)

        # 2. Fair value gaps from the last three candles [D16].
        self.bars.append(bar)
        if len(self.bars) > 400:
            del self.bars[:100]
        if len(self.bars) >= 3:
            first, third = self.bars[-3], self.bars[-1]
            if third[3] > first[2]:
                self.fvgs.append([1, first[2], third[3], t])
            elif third[2] < first[3]:
                self.fvgs.append([-1, third[2], first[3], t])
        # A gap is finished once price closes through it [D18].
        self.fvgs = [g for g in self.fvgs if not ((g[0] == 1 and c < g[1]) or (g[0] == -1 and c > g[2]))][-12:]
        if self.ob is not None and ((self.ob[0] == 1 and c < self.ob[1]) or (self.ob[0] == -1 and c > self.ob[2])):
            self.ob = None

        # 3. Swing points: up candle then down candle is a high, down then up is a low [D6].
        if len(self.bars) >= 2:
            before = self.bars[-2]
            if before[5] == 1 and direction == -1:
                self.swing_high = (max(before[2], h), t)
                self.highs = (self.highs + [self.swing_high[0]])[-20:]
            elif before[5] == -1 and direction == 1:
                self.swing_low = (min(before[3], l), t)
                self.lows = (self.lows + [self.swing_low[0]])[-20:]

        # 4. The current leg, for the 50% line.
        self.leg_low = l if self.leg_low is None else min(self.leg_low, l)
        self.leg_high = h if self.leg_high is None else max(self.leg_high, h)

    def _break(self, direction, bar):
        """The trend flips. The order block is the leg that made the extreme before the break [D10, D20]."""
        self.trend = direction
        self.last_bos = direction
        since = self.swing_high[1] if direction == 1 else self.swing_low[1]
        leg = [b for b in self.bars if b[0] >= since] or self.bars[-1:]
        if leg:
            if direction == 1:
                extreme = min(leg, key=lambda b: b[3])
                self.ob = [1, extreme[3], max(extreme[1], extreme[4]), extreme[0]]   # wick to start of body [D24]
                self.leg_low, self.leg_high = extreme[3], bar[2]
            else:
                extreme = max(leg, key=lambda b: b[2])
                self.ob = [-1, min(extreme[1], extreme[4]), extreme[2], extreme[0]]
                self.leg_low, self.leg_high = bar[3], extreme[2]

    def equilibrium(self):
        if self.leg_low is None:
            return None
        return (self.leg_low + self.leg_high) / 2

    def zones(self, direction):
        """Order block and gaps in one direction: the places a pullback may turn [D20]."""
        out = [g for g in self.fvgs if g[0] == direction]
        if self.ob is not None and self.ob[0] == direction:
            out.append(self.ob)
        return out


def calculate(data):
    count = len(data.close)
    swing_high = np.full(count, np.nan)
    swing_low = np.full(count, np.nan)
    equilibrium = np.full(count, np.nan)
    daily = np.zeros(count)
    four_hour = np.zeros(count)
    window = np.zeros(count)
    if count < 2:
        plot("Swing high", swing_high)
        return
    base = int(data.time[1] - data.time[0]) or 300
    frames = {"m5": Structure(base, base), "h1": Structure(3600, base), "h4": Structure(14400, base), "d1": Structure(86400, base)}
    start, end = _minutes(inputs.start_time), _minutes(inputs.end_time)
    for i in range(count):
        t = int(data.time[i])
        for frame in frames.values():
            frame.add(t, float(data.open[i]), float(data.high[i]), float(data.low[i]), float(data.close[i]))
        m5 = frames["m5"]
        if m5.swing_high is not None:
            swing_high[i] = m5.swing_high[0]
        if m5.swing_low is not None:
            swing_low[i] = m5.swing_low[0]
        eq = frames["h1"].equilibrium()
        if eq is not None:
            equilibrium[i] = eq
        daily[i] = frames["d1"].trend
        four_hour[i] = frames["h4"].trend
        minute = (ny_time(t) % 86400) // 60
        window[i] = 1 if start <= minute < end else 0
    plot("5m swing high", swing_high, color="#9fd3ff", style="dots")
    plot("5m swing low", swing_low, color="#f2b8d6", style="dots")
    plot("1h 50% line", equilibrium, color="#c9b6ff", width=1)
    plot("Daily trend", daily, pane="bias", style="histogram", color="#7fd6a4")
    plot("4h trend", four_hour, pane="bias", color="#ffd27f")
    hline(0, pane="bias", color="#7a7f99")
    plot("Trading window", window, pane="window", style="histogram", color="#7a7f99")
