"""Market data addresses: markets, candles, quotes."""

import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from engine.core.markets import floor_time
from engine.core.models import timeframe_seconds

router = APIRouter()

MAX_CANDLES = 60_000


def candles_payload(candles) -> dict:
    """Candles as columns (much smaller and faster than one object per candle)."""
    return {
        "t": [c.time for c in candles],
        "o": [c.open for c in candles],
        "h": [c.high for c in candles],
        "l": [c.low for c in candles],
        "c": [c.close for c in candles],
        "v": [c.volume for c in candles],
    }


@router.get("/api/markets")
def markets(request: Request):
    engine = request.app.state.engine
    return {"markets": [m.to_dict() for m in engine.catalog.all()], "watchlists": engine.catalog.watchlists}


@router.get("/api/candles")
async def candles(request: Request, symbol: str, timeframe: str = "1m", days: float = 30):
    engine = request.app.state.engine
    started = time.perf_counter()
    try:
        seconds = timeframe_seconds(timeframe)
        engine.catalog.get(symbol)
    except (KeyError, ValueError) as problem:
        return JSONResponse(status_code=400, content={"error": str(problem).strip("'\"")})
    now = engine.clock()
    span = min(days * 86400, MAX_CANDLES * seconds)
    result = await engine.data.history(symbol, timeframe, int(now - span), int(now))
    engine.data.want_live(symbol, timeframe)
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "candles": candles_payload(result["candles"]),
        "gaps": result["gaps"],
        "fetched": result["fetched"],
        "warning": result["warning"],
        "feed": engine.data.feed_status(symbol),
        "milliseconds": round((time.perf_counter() - started) * 1000),
    }


@router.get("/api/quotes")
async def quotes(request: Request, symbols: str):
    """Latest price and change since the start of the UTC day, for the watchlist."""
    engine = request.app.state.engine
    out = {}
    now = engine.clock()
    for symbol in [s for s in symbols.split(",") if s]:
        if symbol not in engine.catalog.markets:
            continue
        engine.data.want_live(symbol, "1m")
        price = engine.data.last_price(symbol)
        day_start = floor_time(now, 86400)
        candles = engine.cache.read(symbol, "1m", day_start, day_start + 120)
        if not candles:
            try:
                hist = await engine.data.history(symbol, "1h", day_start - 3600, int(now))
                candles = [c for c in hist["candles"] if c.time >= day_start] or hist["candles"][-1:]
            except Exception:
                candles = []
        day_open = candles[0].open if candles else None
        if price is None and candles:
            price = candles[-1].close
        change = (price - day_open) / day_open * 100 if price is not None and day_open else None
        out[symbol] = {"price": price, "change_percent": round(change, 2) if change is not None else None, "feed": engine.data.feed_status(symbol)}
    return out
