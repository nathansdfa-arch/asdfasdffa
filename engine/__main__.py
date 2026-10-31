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

# Until remote access is deliberately switched on (phase 12), listen only on
# this computer's private address.
HOST = "127.0.0.1"
REMOTE_HOST = "0.0.0.0"


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
    auth = app.state.auth.status()
    if not auth["remote_enabled"]:
        # log_config=None keeps uvicorn's messages in our own log file and format.
        uvicorn.run(app, host=HOST, port=args.port, log_config=None)
    else:
        run_with_remote_access(app, args.port, auth["remote_port"], log)
    log.info("Engine stopped")


def run_with_remote_access(app, local_port: int, remote_port: int, log) -> None:
    """Serve this computer on the normal port, and other devices over HTTPS on the remote port."""
    import asyncio

    from engine import paths
    from engine.security.auth import make_self_signed_certificate

    tls = paths.data_dir() / "tls"
    cert, key = tls / "cert.pem", tls / "key.pem"
    if not (cert.exists() and key.exists()):
        try:
            cert, key = make_self_signed_certificate(tls)
        except ImportError:
            log.error("Remote access needs the 'cryptography' package for HTTPS. Remote access stays off.")
            uvicorn.run(app, host=HOST, port=local_port, log_config=None)
            return
    log.warning("Remote access is ON: HTTPS on port %d (login and two-factor required)", remote_port)
    local = uvicorn.Server(uvicorn.Config(app, host=HOST, port=local_port, log_config=None))
    remote = uvicorn.Server(uvicorn.Config(
        app, host=REMOTE_HOST, port=remote_port, log_config=None,
        ssl_certfile=str(cert), ssl_keyfile=str(key), lifespan="off",
    ))

    async def both():
        await asyncio.gather(local.serve(), remote.serve())

    asyncio.run(both())


if __name__ == "__main__":
    main()
