"""The trailing drawdown engine (bible section 9).

Plain meanings, used the same way everywhere in the app:

  Equity          closed balance plus open profit or loss, minus fees.
  High-water mark the highest value recorded so far by the firm's method.
  Floor           high-water mark minus the drawdown amount. Touching it fails the account.
  Lock level      where the floor stops rising (often the starting balance). Optional.
  Room left       equity minus the floor.

How the floor moves:
  "intraday"    the high-water mark rises on every price, using equity
  "end_of_day"  the high-water mark rises once a day at the firm's reset, using closed balance
  "static"      the floor never moves (starting balance minus the drawdown amount)

How a breach is measured: on every kind, equity touching the floor at any
moment fails the account, even mid-day on end-of-day plans.
"""

from dataclasses import asdict, dataclass


@dataclass
class DrawdownConfig:
    starting_balance: float
    amount: float                    # the drawdown size, e.g. 1000
    floor_method: str = "intraday"   # intraday, end_of_day, static
    lock_level: float | None = None  # floor stops rising here; None = never locks


@dataclass
class DrawdownState:
    high_water_mark: float
    floor: float
    locked: bool = False
    failed: bool = False
    failed_at_equity: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class TrailingDrawdown:
    def __init__(self, config: DrawdownConfig, state: DrawdownState | None = None):
        if config.floor_method not in ("intraday", "end_of_day", "static"):
            raise ValueError("floor_method must be intraday, end_of_day or static")
        self.config = config
        if state is None:
            hwm = config.starting_balance
            state = DrawdownState(high_water_mark=hwm, floor=self._floor_for(hwm))
            state.locked = self._is_locked(state.floor)
        self.state = state

    def _floor_for(self, high_water_mark: float) -> float:
        floor = high_water_mark - self.config.amount
        if self.config.lock_level is not None:
            floor = min(floor, self.config.lock_level)
        return floor

    def _is_locked(self, floor: float) -> bool:
        return self.config.lock_level is not None and floor >= self.config.lock_level

    def _raise_high_water_mark(self, value: float) -> None:
        if value <= self.state.high_water_mark:
            return
        self.state.high_water_mark = value
        new_floor = self._floor_for(value)
        if new_floor > self.state.floor:     # the floor only ever moves up
            self.state.floor = new_floor
        self.state.locked = self._is_locked(self.state.floor)

    def on_equity(self, equity: float) -> DrawdownState:
        """Call on every price change and every fill."""
        if self.config.floor_method == "intraday":
            self._raise_high_water_mark(equity)
        if not self.state.failed and equity <= self.state.floor:
            self.state.failed = True
            self.state.failed_at_equity = equity
        return self.state

    def on_daily_reset(self, closed_balance: float) -> DrawdownState:
        """Call once at the firm's daily reset time."""
        if self.config.floor_method == "end_of_day":
            self._raise_high_water_mark(closed_balance)
        return self.state

    def room_left(self, equity: float) -> float:
        return equity - self.state.floor
