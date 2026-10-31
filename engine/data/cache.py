"""The local candle cache, so charts and backtests open quickly and work offline.

Candles are stored in the app's SQLite database. Only finished candles are
stored; the candle still forming right now is never cached.
"""

from pathlib import Path

from engine.core.models import Candle
from engine.storage.database import connect


class CandleCache:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def read(self, symbol: str, timeframe: str, start: int, end: int) -> list[Candle]:
        with connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT time, open, high, low, close, volume FROM candles "
                "WHERE symbol = ? AND timeframe = ? AND time BETWEEN ? AND ? ORDER BY time",
                (symbol, timeframe, start, end),
            ).fetchall()
        return [Candle(*row) for row in rows]

    def write(self, symbol: str, timeframe: str, candles: list[Candle]) -> None:
        if not candles:
            return
        with connect(self.db_path) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO candles (symbol, timeframe, time, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [(symbol, timeframe, c.time, c.open, c.high, c.low, c.close, c.volume) for c in candles],
            )

    def coverage(self, symbol: str, timeframe: str) -> tuple[int, int] | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT start, end FROM candle_coverage WHERE symbol = ? AND timeframe = ?", (symbol, timeframe)
            ).fetchone()
        return (row["start"], row["end"]) if row else None

    def set_coverage(self, symbol: str, timeframe: str, start: int, end: int) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO candle_coverage (symbol, timeframe, start, end) VALUES (?, ?, ?, ?)",
                (symbol, timeframe, start, end),
            )


def find_gaps(candles: list[Candle], seconds: int, is_open=lambda t: True) -> list[dict]:
    """Places where candles are missing while the market was open.

    Returns a list of {"from": time, "to": time, "missing": count}, where
    "from" is the last candle before the gap and "to" the first one after.
    """
    gaps = []
    for before, after in zip(candles, candles[1:]):
        if after.time - before.time <= seconds:
            continue
        missing_times = range(before.time + seconds, after.time, seconds)
        missing = sum(1 for t in missing_times if is_open(t))
        if missing:
            gaps.append({"from": before.time, "to": after.time, "missing": missing})
    return gaps
