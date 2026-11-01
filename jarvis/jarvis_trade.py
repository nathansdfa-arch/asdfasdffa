"""jarvis_trade.py: the one tool Jarvis uses to work the trading app.

Jarvis's Claude session runs this from a terminal, for example:

    py jarvis_trade.py status
    py jarvis_trade.py order --account <id> --symbol DEMO:ES --side buy --qty 1 --stop 4990
    py jarvis_trade.py kill-switch

It only talks to the trading app's Jarvis door (/api/jarvis/...) on this
computer, with the Jarvis key. Every order still goes through the app's risk
guard, and the app only lets Jarvis trade paper accounts.

The key: create it in the trading app (Settings, Jarvis, "Create Jarvis key"),
then paste it into a file called jarvis_key.txt next to this script, or set the
TRADING_JARVIS_KEY environment variable. Never commit the key.

Only Python's standard library is used, so it runs with any Python 3.10+.
Answers are printed as JSON. Exit code 0 = done, 1 = the app said no, 2 = couldn't reach the app.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:8765"


def load_key() -> str:
    key = os.environ.get("TRADING_JARVIS_KEY", "").strip()
    if not key:
        path = Path(__file__).with_name("jarvis_key.txt")
        if path.exists():
            key = path.read_text(encoding="utf-8").strip()
    if not key:
        print(json.dumps({"error": "No Jarvis key. Create one in the trading app (Settings, Jarvis) and save it in jarvis_key.txt next to this script."}))
        sys.exit(1)
    return key


def call(url: str, key: str, method: str, path: str, body: dict | None = None) -> int:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url + path, data=data, method=method, headers={"X-Jarvis-Key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=15) as reply:
            result, code = json.loads(reply.read() or b"{}"), 0
    except urllib.error.HTTPError as problem:
        try:
            result = json.loads(problem.read() or b"{}")
        except ValueError:
            result = {"error": f"The app answered {problem.code}."}
        code = 1
    except (urllib.error.URLError, TimeoutError, ConnectionError) as problem:
        print(json.dumps({"error": f"Couldn't reach the trading app at {url}. Is it running? ({problem})"}))
        return 2
    if isinstance(result, dict) and result.get("ok") is False:
        code = 1          # the risk guard blocked it; the reason is in "message"
    print(json.dumps(result, indent=2))
    return code


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Let Jarvis work the trading app (paper accounts, through the risk guard).")
    parser.add_argument("--url", default=os.environ.get("TRADING_APP_URL", DEFAULT_URL), help="the trading app's address")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("status", help="accounts, balances, P&L today, room left, positions")
    commands.add_parser("strategies", help="saved strategy runs and whether each is running")
    for name in ("start-strategy", "stop-strategy"):
        p = commands.add_parser(name, help=f"{name.split('-')[0]} a saved strategy run")
        p.add_argument("run_id")

    p = commands.add_parser("order", help="place an order (a stop is required)")
    p.add_argument("--account", required=True)
    p.add_argument("--symbol", required=True)
    p.add_argument("--side", required=True, choices=["buy", "sell"])
    p.add_argument("--qty", required=True, type=float)
    p.add_argument("--stop", required=True, type=float, help="stop-loss price")
    p.add_argument("--target", type=float, help="take-profit price")
    p.add_argument("--limit", type=float, help="limit price (leave out for a market order)")
    p.add_argument("--autopilot", action="store_true", help="this is Jarvis's own decision (autopilot); needs --reason")
    p.add_argument("--reason", help="why this trade, why now (required with --autopilot)")

    p = commands.add_parser("candles", help="recent price candles for a symbol")
    p.add_argument("--symbol", required=True)
    p.add_argument("--timeframe", default="5m")
    p.add_argument("--count", type=int, default=100)

    commands.add_parser("autopilot", help="is autopilot on, and Jarvis's recent autopilot decisions")

    p = commands.add_parser("move-stop", help="move the stop of an open position")
    p.add_argument("--account", required=True)
    p.add_argument("--symbol", required=True)
    p.add_argument("--price", required=True, type=float)

    p = commands.add_parser("close", help="close one open position")
    p.add_argument("--account", required=True)
    p.add_argument("--symbol", required=True)

    p = commands.add_parser("flatten", help="cancel orders and close every position on an account")
    p.add_argument("--account", required=True)

    commands.add_parser("kill-switch", help="stop all trading at once (only the owner can switch it back on)")
    p = commands.add_parser("log", help="recent guard decisions, fills and alerts")
    p.add_argument("--limit", type=int, default=20)

    args = parser.parse_args(argv)
    key = load_key()
    url = args.url.rstrip("/")
    c = args.command
    if c == "status":
        return call(url, key, "GET", "/api/jarvis/status")
    if c == "strategies":
        return call(url, key, "GET", "/api/jarvis/strategies")
    if c == "start-strategy":
        return call(url, key, "POST", f"/api/jarvis/strategies/{args.run_id}/start")
    if c == "stop-strategy":
        return call(url, key, "POST", f"/api/jarvis/strategies/{args.run_id}/stop")
    if c == "order":
        body = {"account_id": args.account, "symbol": args.symbol, "side": args.side, "quantity": args.qty,
                "stop_loss": args.stop, "take_profit": args.target,
                "order_type": "limit" if args.limit is not None else "market", "price": args.limit,
                "autopilot": args.autopilot, "reason": args.reason}
        return call(url, key, "POST", "/api/jarvis/orders", body)
    if c == "candles":
        query = urllib.parse.urlencode({"symbol": args.symbol, "timeframe": args.timeframe, "limit": args.count})
        return call(url, key, "GET", f"/api/jarvis/candles?{query}")
    if c == "autopilot":
        return call(url, key, "GET", "/api/jarvis/autopilot")
    if c == "move-stop":
        return call(url, key, "POST", "/api/jarvis/positions/stop", {"account_id": args.account, "symbol": args.symbol, "price": args.price})
    if c == "close":
        return call(url, key, "POST", "/api/jarvis/positions/close", {"account_id": args.account, "symbol": args.symbol})
    if c == "flatten":
        return call(url, key, "POST", f"/api/jarvis/accounts/{args.account}/flatten")
    if c == "kill-switch":
        return call(url, key, "POST", "/api/jarvis/kill-switch")
    if c == "log":
        return call(url, key, "GET", f"/api/jarvis/log?limit={args.limit}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
