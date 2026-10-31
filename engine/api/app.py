"""The engine's local API.

Screens talk to the engine by sending small web requests (for example
GET /api/state) and keep a WebSocket (/ws) open for live updates. The
engine also serves the screens themselves (the ui folder).

Security (bible sections 4 and 11):
  - Connections from this computer need no login.
  - Connections from anywhere else are refused unless remote access has been
    switched on (phase 12), and then need a login with a password and a
    two-factor code, over an encrypted connection.
  - Requests whose Host header isn't this computer are refused, which stops
    a web page in your browser from secretly talking to the engine.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from engine import paths
from engine.api import routes_market, routes_scripts, routes_system, routes_trading
from engine.api.live import Client, LiveHub
from engine.runtime import Engine
from engine.security.auth import Auth

log = logging.getLogger(__name__)

LOCAL_ADDRESSES = {"127.0.0.1", "::1", "localhost"}
SESSION_COOKIE = "trading_session"
# Pages and files a remote device may load before logging in.
PUBLIC_PATHS = ("/login.html", "/api/auth/login", "/api/auth/status", "/css/", "/vendor/", "/favicon")


def create_app(db_path: Path | None = None, allow_any_client: bool = False, start_engine: bool = True, engine: Engine | None = None) -> FastAPI:
    """Build the API. Tests pass their own database file and may skip starting live feeds."""
    engine = engine or Engine(db_path or paths.database_path())
    auth = Auth(engine.db_path)
    hub = LiveHub(engine.bus)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        import asyncio
        hub.loop = asyncio.get_running_loop()
        if start_engine:
            await engine.start()
        yield
        if start_engine:
            await engine.stop()

    app = FastAPI(title="Trading App Engine", lifespan=lifespan)
    app.state.engine = engine
    app.state.auth = auth
    app.state.hub = hub

    def is_local(client: str | None) -> bool:
        return allow_any_client or client in LOCAL_ADDRESSES

    @app.middleware("http")
    async def gatekeeper(request: Request, call_next):
        client = request.client.host if request.client else None
        if is_local(client):
            host = (request.headers.get("host") or "").split(":")[0]
            if not allow_any_client and host not in LOCAL_ADDRESSES and host != "testserver":
                return JSONResponse(status_code=403, content={"error": "Refused: unexpected host name."})
            return await call_next(request)
        status = auth.status()
        if not status["remote_enabled"]:
            log.warning("Refused a connection from %s: remote access is switched off", client)
            return JSONResponse(status_code=403, content={"error": "Remote access is switched off. Connect from the computer running the engine."})
        path = request.url.path
        if path.startswith(PUBLIC_PATHS) or auth.session_ok(request.cookies.get(SESSION_COOKIE)):
            return await call_next(request)
        if path.startswith("/api/"):
            return JSONResponse(status_code=401, content={"error": "Please log in."})
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/login.html")

    for module in (routes_system, routes_market, routes_trading, routes_scripts):
        app.include_router(module.router)

    @app.websocket("/ws")
    async def live(websocket: WebSocket):
        client_host = websocket.client.host if websocket.client else None
        if not is_local(client_host):
            if not auth.status()["remote_enabled"] or not auth.session_ok(websocket.cookies.get(SESSION_COOKIE)):
                await websocket.close(code=4401)
                return
        await websocket.accept()
        client = Client(websocket)
        hub.clients.add(client)
        import asyncio
        pump = asyncio.create_task(client.pump())
        try:
            while True:
                message = await websocket.receive_json()
                if message.get("watch"):
                    for item in message["watch"]:
                        try:
                            engine.data.want_live(item["symbol"], item.get("timeframe", "1m"))
                        except (KeyError, ValueError):
                            pass
        except WebSocketDisconnect:
            pass
        finally:
            pump.cancel()
            hub.clients.discard(client)

    # Serve the screens. This goes last so the /api addresses above take priority.
    app.mount("/", StaticFiles(directory=paths.ui_dir(), html=True), name="ui")
    return app
