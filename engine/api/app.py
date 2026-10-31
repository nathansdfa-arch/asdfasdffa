"""The engine's local API.

Screens talk to the engine by sending small web requests to addresses such
as /api/health or /api/settings. The engine also serves the screens
themselves (the files in the ui folder) at the main address.

Security (bible section 11): until remote access is deliberately switched on
in phase 12, the engine only accepts connections from this same computer.
Two layers enforce that:
  1. the server only listens on 127.0.0.1, the address that is reachable
     from this computer and nowhere else (see engine/__main__.py)
  2. every request is checked here, and anything not from this computer is refused
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine import __version__, paths
from engine.storage import database
from engine.storage.settings import SETTINGS, SettingError, SettingsStore

log = logging.getLogger(__name__)

# Addresses that mean "this same computer".
LOCAL_ADDRESSES = {"127.0.0.1", "::1", "localhost"}


class SettingValue(BaseModel):
    value: Any


def create_app(db_path: Path | None = None, allow_any_client: bool = False) -> FastAPI:
    """Build the API. Tests pass their own database file and allow their test client."""
    db_path = db_path or paths.database_path()
    schema_version = database.initialize(db_path)
    settings = SettingsStore(db_path)
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    app = FastAPI(title="Trading App Engine", version=__version__)

    @app.middleware("http")
    async def only_this_computer(request: Request, call_next):
        client = request.client.host if request.client else None
        if not allow_any_client and client not in LOCAL_ADDRESSES:
            log.warning("Refused a connection from %s: remote access is switched off", client)
            return JSONResponse(
                status_code=403,
                content={"error": "Remote access is switched off. Connect from the computer running the engine."},
            )
        return await call_next(request)

    @app.get("/api/health")
    def health() -> dict:
        """Lets a screen check that the engine is running and see basic facts about it."""
        return {
            "status": "ok",
            "version": __version__,
            "started_at": started_at,
            "schema_version": schema_version,
            "data_folder": str(db_path.parent),
        }

    @app.get("/api/settings")
    def get_settings() -> dict:
        """All settings with their labels and current values."""
        values = settings.get_all()
        return {
            key: {"label": spec.label, "value": values[key], "default": spec.default}
            for key, spec in SETTINGS.items()
        }

    @app.put("/api/settings/{key}")
    def put_setting(key: str, body: SettingValue):
        """Save one setting. A bad value gets a plain English reason back."""
        try:
            settings.set(key, body.value)
        except SettingError as problem:
            return JSONResponse(status_code=400, content={"error": str(problem)})
        return {"key": key, "value": body.value}

    # Serve the screens. This goes last so the /api addresses above take priority.
    app.mount("/", StaticFiles(directory=paths.ui_dir(), html=True), name="ui")

    return app
