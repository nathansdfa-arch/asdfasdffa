"""Bybit trading connector for crypto and HyroTrader (phase 11).

Uses Bybit's V5 API with your own API key, which should have trading
permission only and withdrawals disabled (bible section 11). The key and
secret live in Windows Credential Manager, never in the database or logs.

Defaults to Bybit's TESTNET (practice exchange) until the account's broker
settings say "testnet": false. Every order is sent with its stop loss
attached on Bybit's side ("tpslMode": "Full"), so it protects the position
even if the app closes (guard rule 7).

Not tested against Bybit's servers yet, because the build machine's network
blocks Bybit; see NEEDS_NATHAN.md.
"""

import hashlib
import hmac
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

from engine.core.models import AccountSnapshot, Order, OrderRequest, OrderStatus, OrderType, Position, Side
from engine.execution.broker import BrokerConnector, NotConfigured, OrderRefused
from engine.security.credentials import load_secret

log = logging.getLogger(__name__)

LIVE_URL = "https://api.bybit.com"
TESTNET_URL = "https://api-testnet.bybit.com"
RECV_WINDOW = "5000"


class BybitConnector(BrokerConnector):
    name = "Bybit"
    supports_broker_stops = True

    def __init__(self, account_id: str, settings: dict, check_stamp=None, http=None):
        super().__init__(check_stamp)
        self.account_id = account_id
        self.settings = settings
        self.base_url = TESTNET_URL if settings.get("testnet", True) else LIVE_URL
        self.category = settings.get("category", "linear")
        self._http = http or self._default_http
        self._connected = False
        self.status = "Not connected"
        self._cache: dict = {}

    # ---- Signed requests ----------------------------------------------------

    def _keys(self) -> tuple[str, str]:
        key = load_secret(self.account_id, "api_key")
        secret = load_secret(self.account_id, "api_secret")
        if not key or not secret:
            raise NotConfigured("Missing Bybit API key or secret. Add them under Accounts.")
        return key, secret

    @staticmethod
    def _default_http(method: str, url: str, headers: dict, body: str | None) -> dict:
        request = urllib.request.Request(url, data=body.encode() if body else None, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=5) as reply:
            return json.load(reply)

    def _request(self, method: str, path: str, params: dict) -> dict:
        # Reading the account happens on every price tick, so answers are reused for one second.
        cache_key = f"{path}?{sorted(params.items())}"
        if method == "GET":
            cached = self._cache.get(cache_key)
            if cached and time.monotonic() - cached[0] < 1.0:
                return cached[1]
        else:
            self._cache.clear()
        result = self._request_uncached(method, path, params)
        if method == "GET":
            self._cache[cache_key] = (time.monotonic(), result)
        return result

    def _request_uncached(self, method: str, path: str, params: dict) -> dict:
        key, secret = self._keys()
        timestamp = str(int(time.time() * 1000))
        if method == "GET":
            payload = urllib.parse.urlencode(params)
            url, body = f"{self.base_url}{path}?{payload}", None
        else:
            payload = json.dumps(params, separators=(",", ":"))
            url, body = f"{self.base_url}{path}", payload
        signature = hmac.new(secret.encode(), (timestamp + key + RECV_WINDOW + payload).encode(), hashlib.sha256).hexdigest()
        headers = {
            "X-BAPI-API-KEY": key, "X-BAPI-SIGN": signature, "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": RECV_WINDOW, "Content-Type": "application/json",
        }
        try:
            data = self._http(method, url, headers, body)
        except (urllib.error.URLError, OSError) as problem:
            self._connected = False
            self.status = f"Can't reach Bybit: {problem}"
            raise OrderRefused(self.status) from problem
        if data.get("retCode") != 0:
            raise OrderRefused(f"Bybit refused: {data.get('retMsg', 'no reason given')}")
        self._connected = True
        return data.get("result", {})

    # ---- Connection and reading ----------------------------------------------

    def connect(self) -> bool:
        try:
            self._request("GET", "/v5/account/wallet-balance", {"accountType": self.settings.get("account_type", "UNIFIED")})
            self.status = "Connected" + (" (testnet)" if self.base_url == TESTNET_URL else "")
            return True
        except (OrderRefused, NotConfigured) as problem:
            self.status = str(problem)
            self._connected = False
            return False

    @property
    def connected(self) -> bool:
        return self._connected

    def _symbol(self, app_symbol: str) -> str:
        return app_symbol.split(":", 1)[1]

    def snapshot(self, account_id: str) -> AccountSnapshot:
        result = self._request("GET", "/v5/account/wallet-balance", {"accountType": self.settings.get("account_type", "UNIFIED")})
        account = (result.get("list") or [{}])[0]
        equity = float(account.get("totalEquity") or 0)
        open_pnl = float(account.get("totalPerpUPL") or 0)
        return AccountSnapshot(account_id=account_id, balance=equity - open_pnl, open_pnl=open_pnl)

    def _positions_raw(self) -> list[dict]:
        result = self._request("GET", "/v5/position/list", {"category": self.category, "settleCoin": "USDT"})
        return [p for p in result.get("list", []) if float(p.get("size") or 0) > 0]

    def positions(self, account_id: str) -> list[Position]:
        out = []
        for p in self._positions_raw():
            size = float(p["size"]) * (1 if p["side"] == "Buy" else -1)
            out.append(Position(account_id=account_id, symbol=f"BYBIT:{p['symbol']}", quantity=size, average_price=float(p["avgPrice"])))
        return out

    def working_orders(self, account_id: str) -> list[Order]:
        result = self._request("GET", "/v5/order/realtime", {"category": self.category, "settleCoin": "USDT"})
        orders = []
        for o in result.get("list", []):
            kind = OrderType.LIMIT if o["orderType"] == "Limit" else OrderType.MARKET
            if o.get("triggerPrice") and float(o["triggerPrice"]) > 0:
                kind = OrderType.STOP
            role = {"StopLoss": "stop_loss", "TakeProfit": "take_profit"}.get(o.get("stopOrderType", ""), "entry")
            orders.append(Order(
                id=o["orderId"], account_id=account_id, symbol=f"BYBIT:{o['symbol']}",
                side=Side.BUY if o["side"] == "Buy" else Side.SELL, quantity=float(o["qty"]), order_type=kind,
                price=float(o.get("triggerPrice") or o.get("price") or 0) or None, status=OrderStatus.WORKING,
                created_at=int(o.get("createdTime", 0)) / 1000, role=role,
            ))
        # Position-level stops (tpslMode Full) appear on the position, not as orders.
        for p in self._positions_raw():
            for field_name, role, kind in (("stopLoss", "stop_loss", OrderType.STOP), ("takeProfit", "take_profit", OrderType.LIMIT)):
                if p.get(field_name) and float(p[field_name]) > 0 and not any(o.role == role and o.symbol == f"BYBIT:{p['symbol']}" for o in orders):
                    orders.append(Order(
                        id=f"{role}-{p['symbol']}", account_id=account_id, symbol=f"BYBIT:{p['symbol']}",
                        side=Side.SELL if p["side"] == "Buy" else Side.BUY, quantity=float(p["size"]), order_type=kind,
                        price=float(p[field_name]), status=OrderStatus.WORKING, created_at=time.time(), role=role,
                    ))
        return orders

    # ---- Orders ---------------------------------------------------------------

    def _place(self, request: OrderRequest) -> Order:
        params = {
            "category": self.category, "symbol": self._symbol(request.symbol),
            "side": "Buy" if request.side is Side.BUY else "Sell",
            "orderType": "Limit" if request.order_type is OrderType.LIMIT else "Market",
            "qty": f"{request.quantity:g}", "reduceOnly": request.reduce_only, "positionIdx": 0,
        }
        if request.order_type is OrderType.LIMIT:
            params["price"] = f"{request.price:g}"
        if request.order_type is OrderType.STOP:
            params["triggerPrice"] = f"{request.price:g}"
            params["triggerDirection"] = 1 if request.side is Side.BUY else 2
        if request.stop_loss is not None:
            params["stopLoss"] = f"{request.stop_loss:g}"
            params["tpslMode"] = "Full"
            params["slTriggerBy"] = "LastPrice"
        if request.take_profit is not None:
            params["takeProfit"] = f"{request.take_profit:g}"
            params["tpslMode"] = "Full"
        result = self._request("POST", "/v5/order/create", params)
        return Order(
            id=result.get("orderId", ""), account_id=request.account_id, symbol=request.symbol, side=request.side,
            quantity=request.quantity, order_type=request.order_type, price=request.price, status=OrderStatus.WORKING,
            created_at=time.time(), role="close" if request.reduce_only else "entry", source=request.source,
        )

    def _cancel(self, account_id: str, order_id: str) -> None:
        if order_id.startswith(("stop_loss-", "take_profit-")):
            raise OrderRefused("Position stops on Bybit are changed by moving them, not cancelling.")
        symbol = next((o.symbol for o in self.working_orders(account_id) if o.id == order_id), None)
        if symbol is None:
            raise OrderRefused("That order is no longer working.")
        self._request("POST", "/v5/order/cancel", {"category": self.category, "symbol": self._symbol(symbol), "orderId": order_id})

    def _trading_stop(self, symbol: str, **values) -> None:
        params = {"category": self.category, "symbol": self._symbol(symbol), "positionIdx": 0, "tpslMode": "Full"}
        params.update({k: f"{v:g}" if v is not None else "0" for k, v in values.items()})
        self._request("POST", "/v5/position/trading-stop", params)

    def _modify_stop(self, account_id: str, symbol: str, new_stop: float) -> None:
        self._trading_stop(symbol, stopLoss=new_stop)

    def _modify_target(self, account_id: str, symbol: str, new_target: float | None) -> None:
        self._trading_stop(symbol, takeProfit=new_target)

    def _modify_order_price(self, account_id: str, order_id: str, new_price: float) -> None:
        symbol = next((o.symbol for o in self.working_orders(account_id) if o.id == order_id), None)
        if symbol is None:
            raise OrderRefused("That order is no longer working.")
        self._request("POST", "/v5/order/amend", {"category": self.category, "symbol": self._symbol(symbol), "orderId": order_id, "price": f"{new_price:g}"})
