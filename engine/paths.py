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


def is_packaged() -> bool:
    """True when running as the installed Windows app (built with PyInstaller), not from source."""
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """The folder holding the app's own read-only files: ui/, config/ and scripts/examples/.

    From source that is the project folder. In the installed app PyInstaller
    unpacks them into its bundle folder (sys._MEIPASS). The owner's data never
    lives here; see data_dir().
    """
    if is_packaged():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def ui_dir() -> Path:
    """The folder holding the screens (HTML, CSS, JavaScript) that the engine serves."""
    return resource_dir() / "ui"


def config_dir() -> Path:
    """Markets, prop firm rule profiles and signup links."""
    return resource_dir() / "config"


def examples_dir() -> Path:
    """The example scripts loaded on first start."""
    return resource_dir() / "scripts" / "examples"
