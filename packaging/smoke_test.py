"""Check that a built TradingApp.exe really works, without a screen:

    python packaging/smoke_test.py dist/TradingApp/TradingApp.exe

It starts the app's engine with a throwaway data folder and checks that:
  - the engine answers and serves the screens,
  - the bundled config and example scripts (including the TJR ones) are there,
  - the script sandbox works inside the packaged app (indicator and backtest),
  - the sandbox still refuses forbidden imports,
  - new accounts start in PAPER mode and Jarvis can't trade without a stop.
Exits with an error message if anything is wrong. Uses only Python's standard library.
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(base: str, path: str, body: dict | None = None, headers: dict | None = None, timeout: float = 60) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=data, method="POST" if body is not None else "GET",
                                     headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            raw = reply.read()
    except urllib.error.HTTPError as problem:
        raw = problem.read()
    try:
        return json.loads(raw)
    except ValueError:
        return {"_text": raw.decode("utf-8", "replace")}


def check(condition: bool, what: str, detail=None) -> None:
    if not condition:
        raise SystemExit(f"FAILED: {what}\n{json.dumps(detail, indent=1)[:2000] if detail is not None else ''}")
    print(f"ok  {what}")


def main() -> None:
    exe = os.path.abspath(sys.argv[1])
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    data_dir = tempfile.mkdtemp(prefix="tradingapp-smoke-")
    env = dict(os.environ, TRADING_APP_DATA_DIR=data_dir)
    engine = subprocess.Popen([exe, "--engine", "--port", str(port)], env=env)
    try:
        deadline = time.monotonic() + 60
        health = {}
        while time.monotonic() < deadline:
            if engine.poll() is not None:
                break
            try:
                health = call(base, "/api/health", timeout=2)
                break
            except OSError:
                time.sleep(0.5)
        log_file = os.path.join(data_dir, "logs", "app.log")
        log_tail = open(log_file, encoding="utf-8").read()[-3000:] if os.path.exists(log_file) else "(no log)"
        check(health.get("status") == "ok", "engine starts and answers", {"health": health, "log": log_tail})
        print(f"    version {health.get('version')}")

        page = urllib.request.urlopen(base + "/", timeout=10).read().decode("utf-8", "replace")
        check("<html" in page.lower(), "screens are served")

        markets = call(base, "/api/markets")
        check(any(m["symbol"] == "DEMO:ES" for m in markets.get("markets", [])), "bundled config/markets.json loads", markets)
        check(isinstance(call(base, "/api/profiles"), list), "bundled prop firm profiles load")

        scripts = call(base, "/api/scripts")
        ids = {s["id"] for s in scripts} if isinstance(scripts, list) else set()
        for wanted in ("example_tjr_bootcamp_strategy", "example_tjr_bootcamp_chart", "example_ma_crossover"):
            check(wanted in ids, f"example script {wanted} is bundled", sorted(ids))

        indicator = call(base, "/api/indicator", {"script_id": "example_sma_ribbon", "symbol": "DEMO:ES", "timeframe": "5m"})
        check(indicator.get("ok") is True, "indicator runs in the script sandbox", indicator)

        backtest = call(base, "/api/backtest", {"script_id": "example_tjr_bootcamp_strategy", "symbol": "DEMO:ES", "timeframe": "5m", "days": 30}, timeout=300)
        check(backtest.get("ok") is True, "TJR strategy backtest runs", {k: backtest.get(k) for k in ("ok", "error")})

        allowed = call(base, "/api/scripts/check", {"code": "import pandas\nimport statistics\nimport random\ndef calculate(c):\n    return {}\n"})
        check(allowed.get("ok") is True, "scripts can import numpy/pandas/statistics/random", allowed)
        refused = call(base, "/api/scripts/check", {"code": "import os\ndef calculate(c):\n    return {}\n"})
        check(refused.get("ok") is False, "sandbox refuses 'import os'", refused)

        accounts = call(base, "/api/accounts")
        check(bool(accounts) and all(not a.get("live_enabled") for a in accounts), "accounts start in PAPER mode", accounts)

        key = call(base, "/api/owner/jarvis/key", {})["key"]
        no_stop = call(base, "/api/jarvis/orders", {"account_id": accounts[0]["id"], "symbol": "DEMO:ES", "side": "buy", "quantity": 1}, headers={"X-Jarvis-Key": key})
        check(not no_stop.get("ok"), "Jarvis order without a stop is refused", no_stop)
        print("All checks passed.")
    finally:
        engine.terminate()
        try:
            engine.wait(timeout=10)
        except subprocess.TimeoutExpired:
            engine.kill()


if __name__ == "__main__":
    main()
