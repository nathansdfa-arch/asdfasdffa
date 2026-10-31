"""Script addresses: the editor, indicators on charts, backtests, and the Pine helper."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from engine.core.models import timeframe_seconds
from engine.scripting.pine import convert_pine

router = APIRouter()


def bad(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


@router.get("/api/scripts")
def scripts(request: Request):
    return request.app.state.engine.scripts.all()


@router.get("/api/scripts/{script_id}")
def get_script(script_id: str, request: Request):
    try:
        return request.app.state.engine.scripts.get(script_id)
    except KeyError as problem:
        return bad(str(problem), 404)


@router.post("/api/scripts")
async def save_script(request: Request):
    body = await request.json()
    engine = request.app.state.engine
    saved = engine.scripts.save(body.get("id"), body.get("name", ""), body.get("code", ""))
    check = await engine.host.describe(saved["code"])
    return {"script": saved, "check": check}


@router.delete("/api/scripts/{script_id}")
def delete_script(script_id: str, request: Request):
    request.app.state.engine.scripts.delete(script_id)
    return {"deleted": script_id}


@router.post("/api/scripts/check")
async def check_script(request: Request):
    body = await request.json()
    return await request.app.state.engine.host.describe(body.get("code", ""))


async def _candles(engine, symbol: str, timeframe: str, days: float):
    seconds = timeframe_seconds(timeframe)
    now = engine.clock()
    span = min(days * 86400, 60_000 * seconds)
    result = await engine.data.history(symbol, timeframe, int(now - span), int(now))
    return result["candles"]


@router.post("/api/indicator")
async def run_indicator(request: Request):
    """Run an indicator script on a chart's candles. Only finished candles are used unless the script opts in."""
    body = await request.json()
    engine = request.app.state.engine
    code = body.get("code")
    if not code:
        try:
            code = engine.scripts.get(body["script_id"])["code"]
        except KeyError as problem:
            return bad(str(problem).strip("'\""), 404)
    try:
        candles = await _candles(engine, body["symbol"], body.get("timeframe", "1m"), float(body.get("days", 30)))
    except (KeyError, ValueError) as problem:
        return bad(str(problem).strip("'\""))
    if candles and "use_live_candles = True" not in code:
        seconds = timeframe_seconds(body.get("timeframe", "1m"))
        if candles[-1].time + seconds > engine.clock():
            candles = candles[:-1]
    return await engine.host.indicator(code, candles, body["symbol"], body.get("timeframe", "1m"), body.get("inputs"))


@router.post("/api/backtest")
async def backtest(request: Request):
    body = await request.json()
    engine = request.app.state.engine
    try:
        script = engine.scripts.get(body["script_id"])
        candles = await _candles(engine, body["symbol"], body.get("timeframe", "5m"), float(body.get("days", 30)))
    except (KeyError, ValueError) as problem:
        return bad(str(problem).strip("'\""))
    seconds = timeframe_seconds(body.get("timeframe", "5m"))
    candles = [c for c in candles if c.time + seconds <= engine.clock()]     # finished candles only
    if len(candles) < 10:
        return bad("Not enough history for a backtest. Try more days or another symbol.")
    result = await engine.host.backtest(script["code"], candles, body["symbol"], body.get("timeframe", "5m"), float(body.get("starting_balance", 25000)), body.get("inputs"))
    if result.get("ok"):
        result["report"]["symbol"] = body["symbol"]
        result["report"]["timeframe"] = body.get("timeframe", "5m")
        result["report"]["candles"] = len(candles)
        result["report"]["from"] = candles[0].time
        result["report"]["to"] = candles[-1].time
    return result


@router.post("/api/pine/convert")
async def pine(request: Request):
    body = await request.json()
    return convert_pine(body.get("code", ""))
