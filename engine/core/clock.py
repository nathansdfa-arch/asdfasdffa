"""One place to ask "what time is it?".

Tests and backtests swap in a fake clock so they can control time exactly.
Everything is UTC.
"""

import time
from datetime import datetime, timezone


class Clock:
    def now(self) -> float:
        """Unix seconds, UTC, with fractions."""
        return time.time()

    def utc_datetime(self) -> datetime:
        return datetime.fromtimestamp(self.now(), tz=timezone.utc)


class FakeClock(Clock):
    """A clock that only moves when told to. Used by tests and backtests."""

    def __init__(self, start: float = 1_700_000_000.0):
        self.current = start

    def now(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds

    def set(self, value: float) -> None:
        self.current = value


SYSTEM_CLOCK = Clock()
