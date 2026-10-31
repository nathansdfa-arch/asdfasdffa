"""Open the trading app on the desktop:  python -m desktop.launcher

What it does, step by step:
  1. Checks whether the engine is already running. If not, starts it as a
     separate background program.
  2. Waits until the engine answers (up to 20 seconds).
  3. Opens a desktop window showing the app's screens. The window is a small
     Python program (pywebview) that uses the Edge browser built into Windows.
  4. When the window closes, stops the engine if this launcher started it.

Add --browser to open the app in your normal web browser instead of a window.
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


def start_engine(port: int) -> subprocess.Popen:
    """Start the engine as its own program, using the same Python as this launcher."""
    log.info("Starting the engine on port %d", port)
    return subprocess.Popen([sys.executable, "-m", "engine", "--port", str(port)])


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

    webview.create_window("Trading App", url, width=1400, height=900, min_size=(900, 600))
    webview.start()


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
            log.error("The engine did not start. See logs/app.log in the data folder for the reason.")
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
            open_window(url)
    except KeyboardInterrupt:
        pass
    finally:
        if process:
            stop_engine(process)


if __name__ == "__main__":
    main()
