"""Open the trading app on the desktop:  python -m desktop.launcher

What it does, step by step:
  1. Checks whether the engine is already running. If not, starts it as a
     separate background program.
  2. Waits until the engine answers (up to 20 seconds).
  3. Opens a desktop window showing the app's screens. The window is a small
     Python program (pywebview) that uses the Edge browser built into Windows.
  4. When the window closes, stops the engine if this launcher started it.

Add --browser to open the app in your normal web browser instead of a window.

The installed Windows app (TradingApp.exe, see packaging/) runs this same code.
There, the engine is started as "TradingApp.exe --engine" instead of
"python -m engine", and problems are shown in a message box because the app
has no console window.
"""

import argparse
import json
import logging
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

from engine import __version__, paths
from engine.__main__ import DEFAULT_PORT, HOST
from engine.logging_setup import setup_logging

log = logging.getLogger("desktop")

STARTUP_TIMEOUT_SECONDS = 20


def engine_url(port: int) -> str:
    return f"http://{HOST}:{port}"


def engine_is_running(port: int) -> bool:
    """True if a trading app engine answers on this port."""
    try:
        with urllib.request.urlopen(engine_url(port) + "/api/health", timeout=1) as reply:
            return json.load(reply).get("status") == "ok"
    except (urllib.error.URLError, OSError, ValueError):
        return False


def engine_command(port: int) -> list[str]:
    """The command that starts the engine: the installed app runs itself in engine mode."""
    if paths.is_packaged():
        return [sys.executable, "--engine", "--port", str(port)]
    return [sys.executable, "-m", "engine", "--port", str(port)]


def start_engine(port: int) -> subprocess.Popen:
    """Start the engine as its own program, using the same Python as this launcher."""
    log.info("Starting the engine on port %d", port)
    return subprocess.Popen(engine_command(port))


def tell_owner(message: str) -> None:
    """Show a problem to the owner: a Windows message box in the installed app, else the console."""
    log.error(message)
    if sys.platform == "win32" and paths.is_packaged():
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "Trading App", 0x10)   # 0x10 = error icon
    else:
        print(message, file=sys.stderr)


def wait_for_engine(port: int, process: subprocess.Popen | None, timeout: float = STARTUP_TIMEOUT_SECONDS) -> bool:
    """Wait until the engine answers. Gives up early if the engine program has exited."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if engine_is_running(port):
            return True
        if process is not None and process.poll() is not None:
            return False  # the engine crashed during startup; its log says why
        time.sleep(0.2)
    return False


def stop_engine(process: subprocess.Popen) -> None:
    """Ask the engine to stop, and force it if it has not stopped after 5 seconds."""
    if process.poll() is not None:
        return
    log.info("Stopping the engine")
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def open_window(url: str) -> None:
    """Show the app in a desktop window. Returns when the owner closes it."""
    import webview  # pywebview; imported here so --browser works without it

    webview.create_window(f"Trading App {__version__}", url, width=1400, height=900, min_size=(900, 600))
    # private_mode=False keeps what the screens save in the window (the chosen
    # account, custom watchlists) between restarts. It lives in the data folder.
    webview.start(private_mode=False, storage_path=str(paths.data_dir() / "window"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Open the trading app.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--browser", action="store_true", help="use the web browser instead of a desktop window")
    args = parser.parse_args()

    setup_logging()
    process = None
    if engine_is_running(args.port):
        log.info("Engine already running; connecting to it")
    else:
        process = start_engine(args.port)
        if not wait_for_engine(args.port, process):
            tell_owner(
                "The trading engine did not start.\n\n"
                f"The reason is in logs\\app.log inside {paths.data_dir()}"
            )
            if process:
                stop_engine(process)
            sys.exit(1)

    url = engine_url(args.port)
    try:
        if args.browser:
            webbrowser.open(url)
            print(f"The app is open in your browser at {url}. Press Ctrl+C here to stop the engine.")
            while process is None or process.poll() is None:
                time.sleep(1)
        else:
            try:
                open_window(url)
            except Exception:
                # Usually the Microsoft Edge WebView2 Runtime is missing. The browser still works.
                log.exception("The desktop window could not open")
                webbrowser.open(url)
                tell_owner(
                    "The app window could not open, so the app opened in your web browser instead.\n\n"
                    "To fix the window, install the free Microsoft Edge WebView2 Runtime from "
                    "https://developer.microsoft.com/microsoft-edge/webview2/ and start the app again.\n\n"
                    "Close this message to stop the app."
                )
    except KeyboardInterrupt:
        pass
    finally:
        if process:
            stop_engine(process)


if __name__ == "__main__":
    main()
