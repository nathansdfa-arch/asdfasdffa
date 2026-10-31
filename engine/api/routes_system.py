"""System addresses: health, settings, workspaces, drawings, alerts, backups and login."""

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from engine import __version__
from engine.core.markets import CONFIG_DIR
from engine.storage.settings import SETTINGS, SettingError

router = APIRouter()


class SettingValue(BaseModel):
    value: Any


class LoginBody(BaseModel):
    password: str
    code: str


def bad(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


@router.get("/api/health")
def health(request: Request) -> dict:
    engine = request.app.state.engine
    return {
        "status": "ok",
        "version": __version__,
        "started_at": engine.started_at,
        "schema_version": engine.schema_version,
        "data_folder": str(engine.db_path.parent),
    }


@router.get("/api/settings")
def get_settings(request: Request) -> dict:
    values = request.app.state.engine.settings.get_all()
    return {key: {"label": spec.label, "value": values[key], "default": spec.default} for key, spec in SETTINGS.items()}


@router.put("/api/settings/{key}")
async def put_setting(key: str, body: SettingValue, request: Request):
    engine = request.app.state.engine
    try:
        engine.settings.set(key, body.value)
    except SettingError as problem:
        return bad(str(problem))
    if key == "stale_seconds":
        engine.data.stale_after = body.value
    engine.bus.publish("settings", {"key": key, "value": body.value})
    return {"key": key, "value": body.value}


@router.get("/api/state")
def state(request: Request) -> dict:
    """Everything a screen needs when it first opens."""
    engine = request.app.state.engine
    from engine.api.routes_trading import account_view
    return {
        "version": __version__,
        "settings": engine.settings.get_all(),
        "markets": [m.to_dict() for m in engine.catalog.all()],
        "watchlists": engine.catalog.watchlists,
        "accounts": [account_view(engine, a) for a in engine.accounts.all()],
        "trading_halted": engine.guard.trading_halted,
        "providers": engine.data.provider_status,
        "workspaces": engine.workspaces.names(),
        "scripts": engine.scripts.all(),
        "runs": engine.runner.all(),
        "auth": request.app.state.auth.status(),
    }


# ---- Workspaces and drawings ---------------------------------------------------


@router.get("/api/workspaces/{name}")
def get_workspace(name: str, request: Request):
    layout = request.app.state.engine.workspaces.get(name)
    return layout if layout is not None else bad("No such workspace.", 404)


@router.put("/api/workspaces/{name}")
async def save_workspace(name: str, request: Request):
    try:
        request.app.state.engine.workspaces.save(name, await request.json())
    except ValueError as problem:
        return bad(str(problem))
    return {"saved": name}


@router.delete("/api/workspaces/{name}")
def delete_workspace(name: str, request: Request):
    request.app.state.engine.workspaces.delete(name)
    return {"deleted": name}


@router.get("/api/drawings")
def get_drawings(symbol: str, request: Request):
    return request.app.state.engine.drawings.for_symbol(symbol)


@router.put("/api/drawings/{drawing_id}")
async def save_drawing(drawing_id: str, request: Request):
    body = await request.json()
    if "symbol" not in body:
        return bad("A drawing needs a symbol.")
    request.app.state.engine.drawings.save(drawing_id, body["symbol"], body)
    return {"saved": drawing_id}


@router.delete("/api/drawings/{drawing_id}")
def delete_drawing(drawing_id: str, request: Request):
    request.app.state.engine.drawings.delete(drawing_id)
    return {"deleted": drawing_id}


# ---- Logs, alerts and backups ----------------------------------------------------


@router.get("/api/alerts")
def alerts(request: Request, limit: int = 100):
    return request.app.state.engine.journal.alerts(limit)


@router.get("/api/guard-log")
def guard_log(request: Request, limit: int = 200, account_id: str | None = None):
    return request.app.state.engine.journal.decisions(limit, account_id)


@router.get("/api/backups")
def list_backups(request: Request):
    return request.app.state.engine.backups.list()


@router.post("/api/backups")
async def make_backup(request: Request):
    name = await asyncio.to_thread(request.app.state.engine.backups.make)
    return {"saved": name}


@router.get("/api/prop-links")
def prop_links():
    return json.loads((CONFIG_DIR / "prop_firm_links.json").read_text(encoding="utf-8"))["firms"]


# ---- Login and remote access (phase 12) ---------------------------------------------


def _local(request: Request) -> bool:
    return (request.client.host if request.client else None) in ("127.0.0.1", "::1", "localhost", "testclient")


@router.get("/api/auth/status")
def auth_status(request: Request):
    return request.app.state.auth.status()


@router.post("/api/auth/login")
def login(body: LoginBody, request: Request):
    auth = request.app.state.auth
    try:
        token = auth.login(body.password, body.code, request.client.host if request.client else "?")
    except PermissionError as problem:
        return bad(str(problem), 429)
    if not token:
        return bad("The password or the two-factor code is wrong.", 401)
    response = JSONResponse({"ok": True})
    response.set_cookie("trading_session", token, httponly=True, secure=True, samesite="strict", max_age=12 * 3600)
    return response


@router.post("/api/auth/logout")
def logout(request: Request):
    request.app.state.auth.logout(request.cookies.get("trading_session"))
    response = JSONResponse({"ok": True})
    response.delete_cookie("trading_session")
    return response


@router.post("/api/auth/password")
async def set_password(request: Request):
    if not _local(request):
        return bad("Security settings can only be changed on the computer running the engine.", 403)
    body = await request.json()
    try:
        request.app.state.auth.set_password(body.get("password", ""))
    except ValueError as problem:
        return bad(str(problem))
    return {"ok": True}


@router.post("/api/auth/two-factor/start")
def two_factor_start(request: Request):
    if not _local(request):
        return bad("Security settings can only be changed on the computer running the engine.", 403)
    return request.app.state.auth.start_two_factor()


@router.post("/api/auth/two-factor/confirm")
async def two_factor_confirm(request: Request):
    if not _local(request):
        return bad("Security settings can only be changed on the computer running the engine.", 403)
    body = await request.json()
    if not request.app.state.auth.confirm_two_factor(body.get("code", "")):
        return bad("That code didn't match. Check the time on your phone and try the newest code.")
    return {"ok": True}


@router.post("/api/auth/remote")
async def set_remote(request: Request):
    if not _local(request):
        return bad("Remote access can only be switched on or off on the computer running the engine.", 403)
    body = await request.json()
    try:
        request.app.state.auth.set_remote(bool(body.get("enabled")), body.get("port"))
    except ValueError as problem:
        return bad(str(problem))
    return {"ok": True, "note": "Restart the app for this to take effect."}
