"""Logging: a written record of everything the app does.

Logs go to two places:
  - the console window, for quick checks while the app runs
  - logs/app.log in the data folder, kept for later review

The log file is "rotated": when it reaches 5 MB it is renamed app.log.1 and a
fresh file starts, keeping the last 10 files so logs never fill the disk.

Rule from the design bible: never write passwords, API keys or other broker
credentials to the logs.
"""

import logging
import time
from logging.handlers import RotatingFileHandler

from engine import paths

LOG_FORMAT = "%(asctime)s  %(levelname)-7s  %(name)s  %(message)s"

# Remember whether logging is already set up, so calling setup twice is harmless.
_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return

    formatter = logging.Formatter(LOG_FORMAT)
    # Log times in UTC, matching the bible's rule that every stored time is UTC.
    formatter.converter = time.gmtime

    file_handler = RotatingFileHandler(
        paths.logs_dir() / "app.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    _configured = True
    logging.getLogger(__name__).info("Logging started. Log folder: %s", paths.logs_dir())
