"""Where the app keeps its files on disk.

All of the owner's data (database, logs, and later backups) lives in one
"data folder", kept separate from the code so that updating the code never
touches the owner's data.

    Windows:        %LOCALAPPDATA%\\TradingApp   (for example C:\\Users\\you\\AppData\\Local\\TradingApp)
    Other systems:  ~/.trading_app

Setting the TRADING_APP_DATA_DIR environment variable overrides this. The
automated tests use that so they never touch the real data folder.
"""

import os
import sys
from pathlib import Path


def data_dir() -> Path:
    """Return the data folder, creating it if it does not exist yet."""
    override = os.environ.get("TRADING_APP_DATA_DIR")
    if override:
        folder = Path(override)
    elif sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        folder = Path(os.environ["LOCALAPPDATA"]) / "TradingApp"
    else:
        folder = Path.home() / ".trading_app"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def database_path() -> Path:
    """The single SQLite database file that holds settings and, later, trades and scripts."""
    return data_dir() / "trading_app.db"


def logs_dir() -> Path:
    folder = data_dir() / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def ui_dir() -> Path:
    """The folder holding the screens (HTML, CSS, JavaScript) that the engine serves."""
    return Path(__file__).resolve().parent.parent / "ui"
