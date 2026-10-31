"""Phase 1 "done when" test: a saved setting survives a restart.

This starts the real engine as its own program, saves a setting, stops the
engine, starts it again, and checks the setting is still there.
"""

import json
import socket
import urllib.request

from desktop.launcher import engine_url, start_engine, stop_engine, wait_for_engine


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def put_setting(port, key, value):
    request = urllib.request.Request(
        f"{engine_url(port)}/api/settings/{key}",
        data=json.dumps({"value": value}).encode(),
        headers={"Content-Type": "application/json"},
        method="PUT",
    )
    with urllib.request.urlopen(request, timeout=5) as reply:
        assert reply.status == 200


def get_settings(port):
    with urllib.request.urlopen(f"{engine_url(port)}/api/settings", timeout=5) as reply:
        return json.load(reply)


def test_saved_setting_survives_engine_restart():
    port = free_port()

    engine = start_engine(port)
    try:
        assert wait_for_engine(port, engine), "engine did not start"
        put_setting(port, "display_timezone", "Europe/London")
    finally:
        stop_engine(engine)

    engine = start_engine(port)
    try:
        assert wait_for_engine(port, engine), "engine did not restart"
        assert get_settings(port)["display_timezone"]["value"] == "Europe/London"
    finally:
        stop_engine(engine)
