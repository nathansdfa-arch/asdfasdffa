"""The Jarvis door: the only addresses Jarvis (the owner's voice assistant) uses.

Every address here needs the Jarvis key in the X-Jarvis-Key header and Jarvis
switched on in Settings. Orders go through the same order service and risk
guard as every other order, labelled "automation:jarvis", so the guard log
shows which trades were Jarvis's and the guard's runaway limit applies.

What Jarvis can't do is simply not here: switch to live, resume after the kill
switch, change rules or its own limits. Those are owner addresses, protected
by the owner PIN (see app.py).

The /api/owner/... addresses at the bottom are for the owner's Settings screen.
"""

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from engine.core.models import OrderRequest, OrderType, Side
from engine.execution.broker import NotConfigured
from engine.core.models import timeframe_seconds
from engine.security.jarvis import AUTOPILOT_SOURCE, JARVIS_SOURCE

router = APIRouter()


def bad(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


def _door(request: Request, key: str | None) -> JSONResponse | None:
    problem = request.app.state.jarvis.problem_for(key)
    return bad(problem, 403) if problem else None


def _account(engine, account_id: str):
    try:
        return engine.accounts.get(account_id)
    except KeyError:
        return None


def _account_summary(engine, account) -> dict:
    broker = engine.broker_for(account)
    summary = {"id": account.id, "name": account.name, "mode": account.mode, "broker": account.broker,
               "connected": broker.connected, "jarvis_may_trade": engine.jarvis.account_problem(account) is None}
    try:
        if broker.connected:
            numbers = engine.guard.numbers(account)
            summary["numbers"] = {k: numbers.get(k) for k in ("balance", "equity", "open_pnl", "loss_today", "daily_room_left", "guard_room_left", "trades_today", "used", "blocked") if k in numbers}
            summary["positions"] = [p.to_dict() | {"stop": broker.stop_price(account.id, p.symbol), "target": broker.target_price(account.id, p.symbol)} for p in broker.positions(account.id)]
            summary["working_orders"] = [o.to_dict() for o in broker.working_orders(account.id)]
    except NotConfigured as problem:
        summary["problem"] = str(problem)
    state = engine.guard.state(account) if broker.connected else None
    if state:
        summary["halted"] = state.halted or state.failed or state.limit_hit
    return summary


# ---- Jarvis's addresses ------------------------------------------------------------


@router.get("/api/jarvis/status")
def status(request: Request, x_jarvis_key: str | None = Header(default=None)):
    if (refused := _door(request, x_jarvis_key)):
        return refused
    engine = request.app.state.engine
    jarvis = request.app.state.jarvis.status()
    return {
        "trading_halted": engine.guard.trading_halted,
        "jarvis": {k: jarvis[k] for k in ("autopilot_enabled", "max_quantity", "max_orders_per_day", "orders_today")},
        "accounts": [_account_summary(engine, a) for a in engine.accounts.all()],
    }


@router.get("/api/jarvis/strategies")
def strategies(request: Request, x_jarvis_key: str | None = Header(default=None)):
    if (refused := _door(request, x_jarvis_key)):
        return refused
    engine = request.app.state.engine
    return {
        "runs": [{k: r.get(k) for k in ("id", "script_name", "kind", "account_id", "symbol", "timeframe", "active", "status", "last_error")} for r in engine.runner.all()],
        "scripts": [{"id": s["id"], "name": s["name"], "kind": s["kind"]} for s in engine.scripts.all() if s["kind"] in ("strategy", "automation")],
    }


@router.post("/api/jarvis/strategies/{run_id}/start")
def start_strategy(run_id: str, request: Request, x_jarvis_key: str | None = Header(default=None)):
    if (refused := _door(request, x_jarvis_key)):
        return refused
    engine = request.app.state.engine
    run = engine.runner.runs.get(run_id)
    if not run:
        return bad(f"No saved strategy run with id {run_id}.", 404)
    account = _account(engine, run["account_id"])
    if account is None:
        return bad("That run's account no longer exists.", 404)
    if (problem := request.app.state.jarvis.account_problem(account)):
        return bad(problem, 403)
    if engine.runner._source(run) in engine.guard.paused_sources:
        return bad("The guard paused this run for sending too many orders. Only the owner can restart it.", 403)
    try:
        return engine.runner.start(run_id)
    except ValueError as problem:
        return bad(str(problem))


@router.post("/api/jarvis/strategies/{run_id}/stop")
def stop_strategy(run_id: str, request: Request, x_jarvis_key: str | None = Header(default=None)):
    if (refused := _door(request, x_jarvis_key)):
        return refused
    engine = request.app.state.engine
    if run_id not in engine.runner.runs:
        return bad(f"No saved strategy run with id {run_id}.", 404)
    return engine.runner.stop(run_id, "stopped by Jarvis")


class JarvisOrder(BaseModel):
    account_id: str
    symbol: str
    side: str
    quantity: float
    order_type: str = "market"
    price: float | None = None
    stop_loss: float
    take_profit: float | None = None
    autopilot: bool = False          # True when Jarvis decided this trade itself
    reason: str | None = None        # required for autopilot trades


@router.post("/api/jarvis/orders")
def place_order(body: JarvisOrder, request: Request, x_jarvis_key: str | None = Header(default=None)):
    """A new order from Jarvis. A stop is required, then Jarvis's caps, then the full risk guard."""
    if (refused := _door(request, x_jarvis_key)):
        return refused
    engine, jarvis = request.app.state.engine, request.app.state.jarvis
    account = _account(engine, body.account_id)
    if account is None:
        return bad(f"No account with id {body.account_id}.", 404)
    problem = jarvis.account_problem(account) or jarvis.order_problem(body.quantity)
    if body.autopilot:
        problem = problem or jarvis.autopilot_problem(body.reason)
    if problem:
        return bad(problem, 403)
    source = AUTOPILOT_SOURCE if body.autopilot else JARVIS_SOURCE
    try:
        order_request = OrderRequest(
            account_id=body.account_id, symbol=body.symbol, side=Side(body.side), quantity=body.quantity,
            order_type=OrderType(body.order_type), price=body.price, stop_loss=body.stop_loss,
            take_profit=body.take_profit, source=source,
        )
    except ValueError as problem:
        return bad(f"Order not understood: {problem}")
    jarvis.count_order()
    if body.autopilot:
        # Keep Jarvis's own reasoning next to the guard's decision, for review.
        engine.journal.record_decision({
            "time": engine.clock(), "account_id": account.id, "symbol": body.symbol, "action": "autopilot_reason",
            "approved": True, "rule": "Jarvis autopilot", "reason": body.reason.strip()[:1000],
            "numbers": {"side": body.side, "quantity": body.quantity, "stop_loss": body.stop_loss, "take_profit": body.take_profit},
            "source": AUTOPILOT_SOURCE,
        })
    return engine.orders.submit(order_request)


@router.get("/api/jarvis/candles")
async def candles(request: Request, symbol: str, timeframe: str = "5m", limit: int = 100, x_jarvis_key: str | None = Header(default=None)):
    """Recent candles as rows [time, open, high, low, close, volume], oldest first, for Jarvis to read."""
    if (refused := _door(request, x_jarvis_key)):
        return refused
    engine = request.app.state.engine
    try:
        seconds = timeframe_seconds(timeframe)
        engine.catalog.get(symbol)
    except (KeyError, ValueError) as problem:
        return bad(str(problem).strip("'\""))
    limit = max(1, min(limit, 500))
    now = engine.clock()
    result = await engine.data.history(symbol, timeframe, int(now - seconds * (limit + 5)), int(now))
    engine.data.want_live(symbol, timeframe)
    rows = [[c.time, c.open, c.high, c.low, c.close, c.volume] for c in result["candles"]][-limit:]
    return {"symbol": symbol, "timeframe": timeframe, "columns": ["time", "open", "high", "low", "close", "volume"],
            "candles": rows, "last_price": engine.data.last_price(symbol) or (rows[-1][4] if rows else None), "feed": engine.data.feed_status(symbol),
            "warning": result["warning"]}


@router.get("/api/jarvis/autopilot")
def autopilot(request: Request, limit: int = 20, x_jarvis_key: str | None = Header(default=None)):
    """Whether autopilot is on, plus Jarvis's recent autopilot decisions and how the guard answered."""
    if (refused := _door(request, x_jarvis_key)):
        return refused
    engine = request.app.state.engine
    recent = [d for d in engine.journal.decisions(limit=500) if d["source"] == AUTOPILOT_SOURCE][: max(1, min(limit, 100))]
    return {"autopilot_enabled": request.app.state.jarvis.status()["autopilot_enabled"], "recent": recent}


class StopMove(BaseModel):
    account_id: str
    symbol: str
    price: float


@router.post("/api/jarvis/positions/stop")
def move_stop(body: StopMove, request: Request, x_jarvis_key: str | None = Header(default=None)):
    if (refused := _door(request, x_jarvis_key)):
        return refused
    return request.app.state.engine.orders.move_stop(body.account_id, body.symbol, body.price, source=JARVIS_SOURCE)


class PositionRef(BaseModel):
    account_id: str
    symbol: str


@router.post("/api/jarvis/positions/close")
def close_position(body: PositionRef, request: Request, x_jarvis_key: str | None = Header(default=None)):
    if (refused := _door(request, x_jarvis_key)):
        return refused
    return request.app.state.engine.orders.close_position(body.account_id, body.symbol, source=JARVIS_SOURCE)


@router.post("/api/jarvis/accounts/{account_id}/flatten")
def flatten(account_id: str, request: Request, x_jarvis_key: str | None = Header(default=None)):
    if (refused := _door(request, x_jarvis_key)):
        return refused
    if _account(request.app.state.engine, account_id) is None:
        return bad(f"No account with id {account_id}.", 404)
    return request.app.state.engine.orders.flatten_account(account_id, "Jarvis was asked to close everything")


@router.post("/api/jarvis/kill-switch")
async def kill_switch(request: Request, x_jarvis_key: str | None = Header(default=None)):
    if (refused := _door(request, x_jarvis_key)):
        return refused
    return await request.app.state.engine.kill_switch.trigger("Kill switch pressed by Jarvis")


@router.get("/api/jarvis/log")
def guard_log(request: Request, limit: int = 20, x_jarvis_key: str | None = Header(default=None)):
    if (refused := _door(request, x_jarvis_key)):
        return refused
    journal = request.app.state.engine.journal
    limit = max(1, min(limit, 100))
    return {"decisions": journal.decisions(limit=limit), "fills": journal.fills(limit=limit), "alerts": journal.alerts(limit=limit)}


# ---- The owner's addresses (Settings screen; protected by the owner PIN) ---------------


@router.get("/api/owner/jarvis")
def jarvis_settings(request: Request):
    return request.app.state.jarvis.status() | {"pin_set": request.app.state.jarvis.pin_set()}


@router.put("/api/owner/jarvis")
async def change_jarvis_settings(request: Request):
    try:
        return request.app.state.jarvis.configure(await request.json())
    except (ValueError, TypeError) as problem:
        return bad(str(problem))


@router.post("/api/owner/jarvis/key")
def new_jarvis_key(request: Request):
    key = request.app.state.jarvis.new_key()
    return {"key": key, "note": "Copy this key into Jarvis now. It won't be shown again."}


@router.post("/api/owner/pin")
async def set_pin(request: Request):
    body = await request.json()
    try:
        request.app.state.jarvis.set_pin(str(body.get("pin", "")))
    except ValueError as problem:
        return bad(str(problem))
    return {"ok": True}
