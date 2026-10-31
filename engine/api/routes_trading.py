"""Trading addresses: accounts, orders, positions, the kill switch, and strategy/automation runs.

Every order-related address goes through the order service, and so through
the risk guard. There is no address that reaches a broker directly.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from engine.core.models import OrderRequest, OrderType, Side
from engine.execution.accounts import RiskRules
from engine.execution.broker import NotConfigured
from engine.risk.profiles import evaluation_status
from engine.security.credentials import has_secret, save_secret

router = APIRouter()


def bad(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


def account_view(engine, account) -> dict:
    """An account with its live numbers, positions and working orders, for the screens."""
    data = account.to_dict()
    broker = engine.broker_for(account)
    data["broker_connected"] = broker.connected
    data["broker_status"] = getattr(broker, "status", "Connected" if broker.connected else "Not connected")
    try:
        numbers = engine.guard.numbers(account) if broker.connected else {}
        data["numbers"] = numbers
        data["positions"] = [p.to_dict() | {"stop": broker.stop_price(account.id, p.symbol), "target": broker.target_price(account.id, p.symbol), "price": engine.data.last_price(p.symbol)} for p in broker.positions(account.id)]
        data["orders"] = [o.to_dict() for o in broker.working_orders(account.id)]
    except NotConfigured as problem:
        data["numbers"], data["positions"], data["orders"] = {}, [], []
        data["broker_status"] = str(problem)
    profile = None
    if account.profile_id:
        try:
            profile = engine.profiles.get(account.profile_id)
        except KeyError:
            profile = None
    data["profile"] = profile
    data["profile_problem"] = engine.profiles.problem(account)
    data["evaluation"] = evaluation_status(account, data.get("numbers", {}), profile) if data.get("numbers") else None
    data["secrets"] = {name: has_secret(account.id, name) for name in ("password", "api_key", "api_secret")} if account.broker != "paper" else {}
    return data


# ---- Accounts ---------------------------------------------------------------------


class AccountBody(BaseModel):
    name: str
    broker: str = "paper"
    starting_balance: float = 25000.0
    is_prop: bool = False
    profile_id: str | None = None
    safety_buffer: float = 0.0
    rules: dict | None = None
    broker_settings: dict | None = None


@router.get("/api/accounts")
def accounts(request: Request):
    engine = request.app.state.engine
    return [account_view(engine, a) for a in engine.accounts.all()]


@router.post("/api/accounts")
def create_account(body: AccountBody, request: Request):
    engine = request.app.state.engine
    if body.broker not in ("paper", "rithmic", "mt5", "bybit"):
        return bad("Broker must be paper, rithmic, mt5 or bybit.")
    rules = RiskRules.from_dict(body.rules or {})
    rules.safety_buffer = body.safety_buffer
    if body.profile_id:
        try:
            profile = engine.profiles.get(body.profile_id)
        except KeyError as problem:
            return bad(str(problem))
        rules = engine.profiles.rules_for(profile, body.safety_buffer, rules)
    account = engine.create_account(
        body.name.strip() or "Account", broker=body.broker, starting_balance=body.starting_balance,
        is_prop=body.is_prop or bool(body.profile_id), profile_id=body.profile_id, rules=rules,
        broker_settings=body.broker_settings or {},
    )
    return account_view(engine, account)


@router.put("/api/accounts/{account_id}")
async def update_account(account_id: str, request: Request):
    """Change an account's name, rules or broker settings. Live mode has its own address."""
    engine = request.app.state.engine
    try:
        account = engine.accounts.get(account_id)
    except KeyError as problem:
        return bad(str(problem), 404)
    body = await request.json()
    if "name" in body:
        account.name = str(body["name"]).strip() or account.name
    if "rules" in body:
        merged = {**account.rules.__dict__, **body["rules"]}
        account.rules = RiskRules.from_dict(merged)
    if "broker_settings" in body:
        settings = {k: v for k, v in body["broker_settings"].items() if k not in ("password", "api_key", "api_secret")}
        account.broker_settings = settings
    if "profile_id" in body:
        if body["profile_id"]:
            try:
                profile = engine.profiles.get(body["profile_id"])
            except KeyError as problem:
                return bad(str(problem))
            account.rules = engine.profiles.rules_for(profile, account.rules.safety_buffer, account.rules)
            account.is_prop = True
        account.profile_id = body["profile_id"] or None
    engine.accounts.save(account)
    return account_view(engine, engine.accounts.get(account_id))


@router.delete("/api/accounts/{account_id}")
def delete_account(account_id: str, request: Request):
    engine = request.app.state.engine
    account = engine.accounts.get(account_id)
    broker = engine.broker_for(account)
    if broker.connected and broker.positions(account_id):
        return bad("Close this account's positions before removing it.")
    engine.accounts.delete(account_id)
    return {"deleted": account_id}


@router.post("/api/accounts/{account_id}/reset")
def reset_account(account_id: str, request: Request):
    engine = request.app.state.engine
    account = engine.accounts.get(account_id)
    if account.mode == "LIVE":
        return bad("Only paper accounts can be reset.")
    engine.reset_paper_account(account_id)
    return account_view(engine, account)


@router.post("/api/accounts/{account_id}/secret")
async def store_secret(account_id: str, request: Request):
    """Save a password or API key in Windows Credential Manager. It is never stored in the database or logs."""
    if (request.client.host if request.client else "") not in ("127.0.0.1", "::1", "testclient"):
        return bad("Credentials can only be entered on the computer running the engine.", 403)
    body = await request.json()
    name = body.get("name")
    if name not in ("password", "api_key", "api_secret"):
        return bad("Unknown credential.")
    if not save_secret(account_id, name, str(body.get("value", ""))):
        return bad("Secure storage isn't available on this computer.")
    return {"saved": name}


@router.post("/api/accounts/{account_id}/connect")
def connect_account(account_id: str, request: Request):
    engine = request.app.state.engine
    return engine.connect_broker(engine.accounts.get(account_id))


@router.post("/api/accounts/{account_id}/enable-live")
async def enable_live(account_id: str, request: Request):
    """Switch a broker account to LIVE. Needs the exact phrase, a working connection, and no halts."""
    engine = request.app.state.engine
    account = engine.accounts.get(account_id)
    body = await request.json()
    expected = f"LIVE {account.name}"
    if account.broker == "paper":
        return bad("Paper accounts can't trade live. Create a broker account instead.")
    if body.get("confirm") != expected:
        return bad(f'To switch this account to live trading, type exactly: {expected}')
    if engine.profiles.problem(account):
        return bad(engine.profiles.problem(account))
    result = engine.connect_broker(account)
    if not result["ok"]:
        return bad(f"Couldn't connect to the broker: {result['status']}")
    account.live_enabled = True
    account.live_enabled_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    engine.accounts.save(account)
    engine.guard.alert("warning", f"{account.name} switched to LIVE trading.", account.id)
    return account_view(engine, account)


@router.post("/api/accounts/{account_id}/disable-live")
def disable_live(account_id: str, request: Request):
    engine = request.app.state.engine
    account = engine.accounts.get(account_id)
    account.live_enabled = False
    engine.accounts.save(account)
    engine.guard.alert("info", f"{account.name} switched back to PAPER.", account.id)
    return account_view(engine, account)


@router.post("/api/accounts/{account_id}/resume")
def resume_account(account_id: str, request: Request):
    engine = request.app.state.engine
    engine.guard.resume_account(account_id)
    return account_view(engine, engine.accounts.get(account_id))


@router.post("/api/accounts/{account_id}/accept-balance")
def accept_balance(account_id: str, request: Request):
    engine = request.app.state.engine
    engine.guard.accept_broker_balance(account_id)
    return account_view(engine, engine.accounts.get(account_id))


@router.get("/api/accounts/{account_id}/fills")
def fills(account_id: str, request: Request, limit: int = 200):
    return request.app.state.engine.journal.fills(account_id, limit=limit)


@router.get("/api/profiles")
def profiles(request: Request):
    engine = request.app.state.engine
    return [p | {"missing": engine.profiles.missing(p)} for p in engine.profiles.all()]


# ---- Orders -------------------------------------------------------------------------


class OrderBody(BaseModel):
    account_id: str
    symbol: str
    side: str
    quantity: float
    order_type: str = "market"
    price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    source: str = "manual"


@router.post("/api/orders")
async def place_order(body: OrderBody, request: Request):
    engine = request.app.state.engine
    try:
        order_request = OrderRequest(
            account_id=body.account_id, symbol=body.symbol, side=Side(body.side), quantity=body.quantity,
            order_type=OrderType(body.order_type), price=body.price, stop_loss=body.stop_loss,
            take_profit=body.take_profit, source=body.source if body.source in ("manual", "chart", "phone") else "manual",
        )
    except ValueError as problem:
        return bad(f"Order not understood: {problem}")
    return engine.orders.submit(order_request)


@router.post("/api/orders/cancel")
async def cancel_order(request: Request):
    body = await request.json()
    return request.app.state.engine.orders.cancel(body["account_id"], body["order_id"])


@router.post("/api/orders/move")
async def move_order(request: Request):
    body = await request.json()
    return request.app.state.engine.orders.move_order(body["account_id"], body["order_id"], float(body["price"]))


@router.post("/api/positions/stop")
async def move_stop(request: Request):
    body = await request.json()
    return request.app.state.engine.orders.move_stop(body["account_id"], body["symbol"], float(body["price"]))


@router.post("/api/positions/target")
async def move_target(request: Request):
    body = await request.json()
    price = body.get("price")
    return request.app.state.engine.orders.move_target(body["account_id"], body["symbol"], float(price) if price is not None else None)


@router.post("/api/positions/close")
async def close_position(request: Request):
    body = await request.json()
    return request.app.state.engine.orders.close_position(body["account_id"], body["symbol"])


@router.post("/api/accounts/{account_id}/flatten")
async def flatten(account_id: str, request: Request):
    return request.app.state.engine.orders.flatten_account(account_id, "owner pressed close all")


# ---- Kill switch ----------------------------------------------------------------------


@router.post("/api/kill-switch")
async def kill_switch(request: Request):
    """One press, no confirmation (bible section 9)."""
    return await request.app.state.engine.kill_switch.trigger("Kill switch pressed by the owner")


@router.post("/api/trading/resume")
def resume_trading(request: Request):
    request.app.state.engine.kill_switch.resume()
    return {"trading_halted": False}


@router.post("/api/sources/resume")
async def resume_source(request: Request):
    body = await request.json()
    request.app.state.engine.guard.resume_source(body["source"])
    return {"resumed": body["source"]}


# ---- Strategy and automation runs ---------------------------------------------------------


@router.get("/api/runs")
def runs(request: Request):
    return request.app.state.engine.runner.all()


@router.post("/api/runs")
async def create_run(request: Request):
    body = await request.json()
    try:
        return request.app.state.engine.runner.create(body["script_id"], body["account_id"], body.get("symbol"), body.get("timeframe"), body.get("inputs"))
    except (KeyError, ValueError) as problem:
        return bad(str(problem).strip("'\""))


@router.post("/api/runs/{run_id}/start")
def start_run(run_id: str, request: Request):
    try:
        return request.app.state.engine.runner.start(run_id)
    except (KeyError, ValueError) as problem:
        return bad(str(problem).strip("'\""))


@router.post("/api/runs/{run_id}/stop")
def stop_run(run_id: str, request: Request):
    return request.app.state.engine.runner.stop(run_id)


@router.delete("/api/runs/{run_id}")
def delete_run(run_id: str, request: Request):
    request.app.state.engine.runner.delete(run_id)
    return {"deleted": run_id}
