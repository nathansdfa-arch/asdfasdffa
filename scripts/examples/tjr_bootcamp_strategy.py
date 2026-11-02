# TJR Boot Camp strategy.
#
# The rules come from the strategy write-up made from TJR's Boot Camp videos
# (Days 1-55). Day numbers like [D6] say which video a rule comes from.
#
# Run it on a 5 minute chart. The script builds the 15 minute, 1 hour,
# 4 hour and daily candles itself from the 5 minute ones.
#
#   1. Bias: the daily trend is the direction of the last daily break of
#      structure. The 4 hour (and, if switched on, the 1 hour) must agree [D34-36].
#   2. Point of interest: price must trade into a 1 hour or 4 hour order block
#      or fair value gap in the bias direction [D20, D22, D49].
#   3. In the window (9:30 to 11:00 New York time) [D29]: the 5 minute chart
#      sweeps liquidity against the bias, then breaks structure with the bias,
#      with a candle body closing past the latest swing [D6, D30].
#   4. Entry on the pullback into the 5 minute order block (model 2) or after a
#      reaction in the 5 minute fair value gap (model 3). Model 1, entering
#      straight on the break, is off because TJR dropped it [D41].
#   5. Stop past the sweep, plus a buffer [D38]. First target is the nearest
#      15 minute liquidity, and it must be at least 1:1 [D37]. At the first
#      target, half comes off and the stop moves to break-even [D53].
#   6. One trade a day, win or lose [D21, D29]. Everything is closed before the
#      end of the New York session; no overnight holds [D36].
#
# What it can't know: the news calendar. Put CPI, PPI, FOMC, NFP, Fed Chair
# and bank holiday dates in skip_dates, like "2026-11-13, 2026-11-27" [D19].
#
# Size: risk_dollars / (stop distance x point_value). Set point_value for the
# market you trade (S&P futures ES = 50, MES = 5, most CFDs = 1).

name = "TJR Boot Camp strategy"
inputs = {
    "risk_dollars": 250,         # money lost if the stop is hit (1% of a 25K account) [D27]
    "point_value": 50,           # money per 1.0 price move per 1 contract or lot
    "quantity_step": 1,          # smallest size step at your broker
    "require_1h_agrees": True,   # the 1 hour trend must match the daily bias as well as the 4 hour
    "require_discount": False,   # model 4: only buy below (sell above) the 50% line of the move [D26]
    "allow_model_1": False,      # enter straight on the break of structure (TJR dropped this) [D41]
    "start_time": "09:30",       # New York time [D29]
    "end_time": "11:00",
    "flatten_time": "15:50",     # close anything still open
    "london_window": False,      # also trade 03:00 to 04:30 New York time (London open) [D29]
    "confirm_bars": 12,          # a sweep must be followed by a break within this many candles [D12]
    "min_rr_tp1": 1.0,           # first target must be at least this many times the risk [D37]
    "final_target_r": 3.0,       # last target in R if there is no 1 hour liquidity further out
    "stop_buffer": 0.5,          # extra room past the sweep, in price (spread) [D38]
    "skip_dates": "",            # news days to sit out, as YYYY-MM-DD, comma separated [D19]
}
lookback = 2000

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


# ---------------------------------------------------------------------------
# The strategy
# ---------------------------------------------------------------------------

_state = {}


def _reset(base_seconds):
    _state.clear()
    _state.update({
        "base": base_seconds,
        "last_time": None,
        "m5": Structure(base_seconds, base_seconds),
        "m15": Structure(900, base_seconds),
        "h1": Structure(3600, base_seconds),
        "h4": Structure(14400, base_seconds),
        "d1": Structure(86400, base_seconds),
        "day": None,
        "traded_today": False,
        "armed": False,
        "sweep": None,       # [extreme, bars since]
        "setup": None,       # the confirmed setup waiting for its pullback
        "trade": None,       # the trade being managed
    })


def _skip_days():
    return {d.strip() for d in str(inputs.skip_dates).split(",") if d.strip()}


def _in_window(minute):
    if _minutes(inputs.start_time) <= minute < _minutes(inputs.end_time):
        return True
    return bool(inputs.london_window) and 180 <= minute < 270


def _beyond(a, b, direction):
    """True when a is past b in the trade's direction (above for longs, below for shorts)."""
    return (a - b) * direction > 0


def _size(risk_points):
    step = float(inputs.quantity_step) or 1.0
    raw = float(inputs.risk_dollars) / (risk_points * float(inputs.point_value))
    return math.floor(raw / step) * step


def _plan_entry(direction, price, sweep_extreme):
    """Stop past the sweep, first target at 15 minute liquidity, last target at 1 hour liquidity."""
    stop = sweep_extreme - direction * float(inputs.stop_buffer)
    risk = (price - stop) * direction
    if risk <= 0:
        return None
    m15, h1, m5 = _state["m15"], _state["h1"], _state["m5"]
    pools = (m15.highs + m5.highs) if direction == 1 else (m15.lows + m5.lows)
    ahead = [p for p in pools if _beyond(p, price, direction)]
    if not ahead:
        return None
    tp1 = min(ahead) if direction == 1 else max(ahead)
    if (tp1 - price) * direction < float(inputs.min_rr_tp1) * risk:
        return None   # less than 1:1 to the first target: wait or skip [D26, D37]
    far = [p for p in (h1.highs if direction == 1 else h1.lows) if _beyond(p, tp1, direction)]
    if far:
        final = min(far) if direction == 1 else max(far)
    else:
        final = price + direction * float(inputs.final_target_r) * risk
    quantity = _size(risk)
    if quantity <= 0:
        return None
    return {"direction": direction, "stop": stop, "tp1": tp1, "final": final, "quantity": quantity, "risk": risk}


def _enter(plan, reason):
    if plan["direction"] == 1:
        buy(plan["quantity"], stop=plan["stop"], target=plan["final"])
    else:
        sell(plan["quantity"], stop=plan["stop"], target=plan["final"])
    side = "Long" if plan["direction"] == 1 else "Short"
    alert(f"{side} {plan['quantity']:g}: {reason}. Stop {plan['stop']:.2f}, first target {plan['tp1']:.2f}, last target {plan['final']:.2f}.")
    _state["trade"] = {**plan, "partial_done": False}
    _state["traded_today"] = True
    _state["setup"] = None
    _state["sweep"] = None
    _state["armed"] = False


def _manage(data, position):
    """Half off at the first target and stop to break-even [D53]; flat before the session ends."""
    trade = _state["trade"]
    t = int(data.time[-1])
    minute = (ny_time(t) % 86400) // 60
    if minute >= _minutes(inputs.flatten_time):
        close()
        alert("Closing before the end of the session. TJR doesn't hold overnight [D36].")
        return
    if trade is None or trade["partial_done"]:
        return
    direction = 1 if position.is_long else -1
    reached = data.high[-1] >= trade["tp1"] if direction == 1 else data.low[-1] <= trade["tp1"]
    if reached:
        step = float(inputs.quantity_step) or 1.0
        half = math.floor(abs(position.size) / 2 / step) * step
        if half > 0:
            if direction == 1:
                sell(half, stop=position.entry_price)
            else:
                buy(half, stop=position.entry_price)
            alert("First target reached: half off, stop to break-even [D53].")
        trade["partial_done"] = True


def on_bar(data, position):
    count = len(data.close)
    if count < 2:
        return
    base = int(data.time[-1] - data.time[-2]) or 300
    if not _state or _state["base"] != base or (_state["last_time"] is not None and data.time[-1] <= _state["last_time"]):
        _reset(base)

    # Feed every candle we haven't seen yet into all the timeframes.
    for i in range(count):
        t = int(data.time[i])
        if _state["last_time"] is not None and t <= _state["last_time"]:
            continue
        for key in ("m5", "m15", "h1", "h4", "d1"):
            _state[key].add(t, float(data.open[i]), float(data.high[i]), float(data.low[i]), float(data.close[i]))
        _state["last_time"] = t

    t = int(data.time[-1])
    local = ny_time(t)
    day = local // 86400
    minute = (local % 86400) // 60
    if day != _state["day"]:
        _state.update({"day": day, "traded_today": False, "armed": False, "sweep": None, "setup": None})

    if not position.is_flat:
        _manage(data, position)
        return
    _state["trade"] = None
    if _state["traded_today"]:
        return   # one trade a day, win or lose [D21, D29]

    moment = datetime.datetime.fromtimestamp(local, datetime.timezone.utc)
    date_text = f"{moment.year:04d}-{moment.month:02d}-{moment.day:02d}"
    weekday = moment.weekday()
    if weekday >= 5 or date_text in _skip_days():
        return

    # 1. Bias from the daily, confirmed by the 4 hour (and 1 hour) [D34-36, D44, D49].
    d1, h4, h1, m5 = _state["d1"], _state["h4"], _state["h1"], _state["m5"]
    bias = d1.trend
    if bias == 0 or h4.trend != bias or (inputs.require_1h_agrees and h1.trend != bias):
        _state["armed"] = False
        _state["sweep"] = None
        _state["setup"] = None
        return

    o, h, l, c = float(data.open[-1]), float(data.high[-1]), float(data.low[-1]), float(data.close[-1])

    # 2. Armed once price reaches a 1 hour or 4 hour zone in the bias direction.
    #    A touch before the open can arm it; only the window can trigger [D18].
    if not _state["armed"]:
        for zone in h1.zones(bias) + h4.zones(bias):
            if l <= zone[2] and h >= zone[1]:
                _state["armed"] = True
                break
    if not _state["armed"] or not _in_window(minute):
        return

    # 4. A confirmed setup waits for its pullback.
    setup = _state["setup"]
    if setup is not None:
        if _beyond(setup["extreme"], c, bias):
            _state["setup"] = None    # price went back past the sweep: the idea is wrong [D38]
            return
        if inputs.require_discount and not _beyond(setup["eq"], c, bias) and c != setup["eq"]:
            return
        ob = setup["ob"]
        if ob is not None and l <= ob[2] and h >= ob[1]:
            plan = _plan_entry(bias, c, setup["extreme"])
            if plan:
                _enter(plan, "sweep, break of structure, pullback into the 5 minute order block (model 2)")
            return
        for gap in setup["fvgs"]:
            touched = l <= gap[2] and h >= gap[1]
            reacted = (c > o) if bias == 1 else (c < o)
            if touched and reacted:
                plan = _plan_entry(bias, c, setup["extreme"])
                if plan:
                    _enter(plan, "sweep, break of structure, reaction in the 5 minute fair value gap (model 3)")
                return
        return

    # 3. Sweep against the bias, then a body close past the latest swing with the bias [D6, D12, D30].
    sweep = _state["sweep"]
    level = m5.swing_low if bias == 1 else m5.swing_high
    if sweep is None:
        if level is not None and _beyond(level[0], l if bias == 1 else h, bias):
            _state["sweep"] = {"extreme": l if bias == 1 else h, "time": t, "bars": 0}
        return
    sweep["bars"] += 1
    sweep["extreme"] = min(sweep["extreme"], l) if bias == 1 else max(sweep["extreme"], h)
    if sweep["bars"] > int(inputs.confirm_bars):
        _state["sweep"] = None   # no reaction, no trade [D12]
        return
    swing = m5.swing_high if bias == 1 else m5.swing_low
    if swing is not None and _beyond(c, swing[0], bias):
        leg = [b for b in m5.bars if b[0] >= sweep["time"]]
        extreme_bar = min(leg, key=lambda b: b[3]) if bias == 1 else max(leg, key=lambda b: b[2])
        if bias == 1:
            ob = [1, extreme_bar[3], max(extreme_bar[1], extreme_bar[4]), extreme_bar[0]]
            eq = (sweep["extreme"] + max(b[2] for b in leg)) / 2
        else:
            ob = [-1, min(extreme_bar[1], extreme_bar[4]), extreme_bar[2], extreme_bar[0]]
            eq = (sweep["extreme"] + min(b[3] for b in leg)) / 2
        gaps = [g for g in m5.fvgs if g[0] == bias and g[3] >= sweep["time"]]
        _state["sweep"] = None
        if inputs.allow_model_1:
            plan = _plan_entry(bias, c, sweep["extreme"])
            if plan:
                _enter(plan, "sweep and break of structure (model 1)")
                return
        _state["setup"] = {"extreme": sweep["extreme"], "ob": ob, "fvgs": gaps, "eq": eq}
