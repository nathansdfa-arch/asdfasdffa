"""Start the engine on its own:  python -m engine

Normally the desktop launcher starts the engine for you. Running it directly
is useful for testing, or for using the app in a browser on this computer at
http://127.0.0.1:8765
"""

import argparse
import logging

import uvicorn

from engine import __version__
from engine.api.app import create_app
from engine.logging_setup import setup_logging

DEFAULT_PORT = 8765

# FIXED until phase 12: listen only on this computer's private address.
HOST = "127.0.0.1"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the trading app engine.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="port number to listen on")
    args = parser.parse_args()

    setup_logging()
    log = logging.getLogger("engine")
    log.info("Engine %s starting on http://%s:%d", __version__, HOST, args.port)

    # The screens check the engine every 2 seconds. Logging each of those
    # requests would flood the log file, so only problems are logged for them.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    app = create_app()
    # log_config=None keeps uvicorn's messages in our own log file and format.
    uvicorn.run(app, host=HOST, port=args.port, log_config=None)
    log.info("Engine stopped")


if __name__ == "__main__":
    main()
