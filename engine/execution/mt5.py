"""MetaTrader 5 connector for forex and CFDs (phase 10).

Uses MetaQuotes' official "MetaTrader5" Python package, which only works on
Windows, next to a running MetaTrader 5 terminal that is logged in to your
broker (bible section 10). Not tested against a real terminal yet, because
the build machine isn't Windows; see NEEDS_NATHAN.md.

Symbols: the app calls them "MT5:EURUSD" and so on. Some brokers add
suffixes (EURUSD.m); set "symbol_suffix" in the account's broker settings.

Stops: every order is sent with its stop loss ("sl") attached on the
broker's server, so it protects the account even if the app closes (rule 7).
"""

import asyncio
import logging
import time

from engine.core.models import AccountSnapshot, Candle, Order, OrderRequest, OrderStatus, OrderType, Position, Side, Tick
from engine.data.provider import DataProvider, ProviderError
from engine.execution.broker import BrokerConnector, NotConfigured, OrderRefused
from engine.security.credentials import load_secret

log = logging.getLogger(__name__)

MAGIC = 260_101       # tags orders placed by this app
DEVIATION_POINTS = 20  # allowed price movement while a market order is sent


def _mt5():
    try:
        import MetaTrader5 as mt5   # Windows only
        return mt5
    except ImportError:
        return None


def mt5_available() -> bool:
    return _mt5() is not None


class MT5Connector(BrokerConnector):
    name = "MetaTrader 5"
    supports_broker_stops = True

    def __init__(self, account_id: str, settings: dict, check_stamp=None):
        super().__init__(check_stamp)
        self.account_id = account_id
        self.settings = settings
        self.suffix = settings.get("symbol_suffix", "")
        self._connected = False
        self.status = "Not connected"

    # ---- Connection ---------------------------------------------------------

    def connect(self) -> bool:
        mt5 = _mt5()
        if mt5 is None:
            self.status = "The MetaTrader5 package isn't installed or this isn't Windows."
            return False
        login = self.settings.get("login")
        server = self.settings.get("server")
        password = load_secret(self.account_id, "password")
        if not (login and server and password):
            self.status = "Missing login, server or password. Fill them in under Accounts."
            return False
        kwargs = {"login": int(login), "server": server, "password": password}
        if self.settings.get("terminal_path"):
            kwargs["path"] = self.settings["terminal_path"]
        if not mt5.initialize(**kwargs):
            self.status = f"MetaTrader 5 refused the connection: {mt5.last_error()}"
            return False
        self._connected = True
        self.status = "Connected"
        return True

    @property
    def connected(self) -> bool:
        mt5 = _mt5()
        return bool(self._connected and mt5 and mt5.terminal_info() is not None)

    def _symbol(self, app_symbol: str) -> str:
        return app_symbol.split(":", 1)[1] + self.suffix

    def _app_symbol(self, mt5_symbol: str) -> str:
        if self.suffix and mt5_symbol.endswith(self.suffix):
            mt5_symbol = mt5_symbol[: -len(self.suffix)]
        return f"MT5:{mt5_symbol}"

    # ---- Reading the account -------------------------------------------------

    def snapshot(self, account_id: str) -> AccountSnapshot:
        mt5 = _mt5()
        if not self.connected:
            raise NotConfigured(self.status)
        info = mt5.account_info()
        return AccountSnapshot(account_id=account_id, balance=float(info.balance), open_pnl=float(info.equity - info.balance))

    def positions(self, account_id: str) -> list[Position]:
        mt5 = _mt5()
        if not self.connected:
            return []
        result = []
        for p in mt5.positions_get() or []:
            signed = p.volume if p.type == mt5.POSITION_TYPE_BUY else -p.volume
            result.append(Position(account_id=account_id, symbol=self._app_symbol(p.symbol), quantity=signed, average_price=p.price_open))
        return result

    def working_orders(self, account_id: str) -> list[Order]:
        mt5 = _mt5()
        if not self.connected:
            return []
        orders = []
        for o in mt5.orders_get() or []:
            buy = o.type in (mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP)
            kind = OrderType.LIMIT if o.type in (mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_SELL_LIMIT) else OrderType.STOP
            orders.append(Order(
                id=str(o.ticket), account_id=account_id, symbol=self._app_symbol(o.symbol),
                side=Side.BUY if buy else Side.SELL, quantity=o.volume_current, order_type=kind,
                price=o.price_open, status=OrderStatus.WORKING, created_at=float(o.time_setup),
            ))
        # MT5 keeps stops on the position itself; show them as stop orders so the guard can see them.
        for p in mt5.positions_get() or []:
            if p.sl:
                orders.append(Order(
                    id=f"sl-{p.ticket}", account_id=account_id, symbol=self._app_symbol(p.symbol),
                    side=Side.SELL if p.type == mt5.POSITION_TYPE_BUY else Side.BUY, quantity=p.volume,
                    order_type=OrderType.STOP, price=p.sl, status=OrderStatus.WORKING, created_at=float(p.time), role="stop_loss",
                ))
            if p.tp:
                orders.append(Order(
                    id=f"tp-{p.ticket}", account_id=account_id, symbol=self._app_symbol(p.symbol),
                    side=Side.SELL if p.type == mt5.POSITION_TYPE_BUY else Side.BUY, quantity=p.volume,
                    order_type=OrderType.LIMIT, price=p.tp, status=OrderStatus.WORKING, created_at=float(p.time), role="take_profit",
                ))
        return orders

    # ---- Orders ----------------------------------------------------------------

    def _send(self, request: dict):
        mt5 = _mt5()
        result = mt5.order_send(request)
        if result is None or result.retcode not in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED):
            message = getattr(result, "comment", None) or str(mt5.last_error())
            raise OrderRefused(f"MetaTrader 5 refused the order: {message}")
        return result

    def _place(self, request: OrderRequest) -> Order:
        mt5 = _mt5()
        if not self.connected:
            raise OrderRefused(self.status)
        symbol = self._symbol(request.symbol)
        tick = mt5.symbol_info_tick(symbol)
        buy = request.side is Side.BUY
        if request.reduce_only:
            return self._close(request, symbol)
        if request.order_type is OrderType.MARKET:
            action, kind, price = mt5.TRADE_ACTION_DEAL, (mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL), (tick.ask if buy else tick.bid)
        elif request.order_type is OrderType.LIMIT:
            action, kind, price = mt5.TRADE_ACTION_PENDING, (mt5.ORDER_TYPE_BUY_LIMIT if buy else mt5.ORDER_TYPE_SELL_LIMIT), request.price
        else:
            action, kind, price = mt5.TRADE_ACTION_PENDING, (mt5.ORDER_TYPE_BUY_STOP if buy else mt5.ORDER_TYPE_SELL_STOP), request.price
        payload = {
            "action": action, "symbol": symbol, "volume": float(request.quantity), "type": kind, "price": float(price),
            "deviation": DEVIATION_POINTS, "magic": MAGIC, "comment": request.source[:30],
            "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC,
        }
        if request.stop_loss is not None:
            payload["sl"] = float(request.stop_loss)
        if request.take_profit is not None:
            payload["tp"] = float(request.take_profit)
        result = self._send(payload)
        return Order(
            id=str(result.order), account_id=request.account_id, symbol=request.symbol, side=request.side,
            quantity=request.quantity, order_type=request.order_type, price=request.price,
            status=OrderStatus.FILLED if action == mt5.TRADE_ACTION_DEAL else OrderStatus.WORKING,
            created_at=time.time(), source=request.source,
        )

    def _close(self, request: OrderRequest, symbol: str) -> Order:
        mt5 = _mt5()
        tick = mt5.symbol_info_tick(symbol)
        remaining = request.quantity
        for p in mt5.positions_get(symbol=symbol) or []:
            if remaining <= 0:
                break
            volume = min(p.volume, remaining)
            sell = p.type == mt5.POSITION_TYPE_BUY
            self._send({
                "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": volume, "position": p.ticket,
                "type": mt5.ORDER_TYPE_SELL if sell else mt5.ORDER_TYPE_BUY, "price": tick.bid if sell else tick.ask,
                "deviation": DEVIATION_POINTS, "magic": MAGIC, "comment": "close",
                "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC,
            })
            remaining -= volume
        return Order(id=f"close-{int(time.time() * 1000)}", account_id=request.account_id, symbol=request.symbol, side=request.side,
                     quantity=request.quantity, order_type=OrderType.MARKET, price=None, status=OrderStatus.FILLED,
                     created_at=time.time(), role="close", source=request.source)

    def _cancel(self, account_id: str, order_id: str) -> None:
        mt5 = _mt5()
        if order_id.startswith(("sl-", "tp-")):
            raise OrderRefused("Stops and targets in MetaTrader 5 are changed by moving them, not cancelling.")
        self._send({"action": mt5.TRADE_ACTION_REMOVE, "order": int(order_id)})

    def _set_sltp(self, symbol: str, sl=None, tp=None, change_sl=False, change_tp=False) -> None:
        mt5 = _mt5()
        for p in mt5.positions_get(symbol=self._symbol(symbol)) or []:
            self._send({
                "action": mt5.TRADE_ACTION_SLTP, "symbol": p.symbol, "position": p.ticket,
                "sl": float(sl) if change_sl else p.sl, "tp": float(tp or 0) if change_tp else p.tp,
            })

    def _modify_stop(self, account_id: str, symbol: str, new_stop: float) -> None:
        self._set_sltp(symbol, sl=new_stop, change_sl=True)

    def _modify_target(self, account_id: str, symbol: str, new_target: float | None) -> None:
        self._set_sltp(symbol, tp=new_target, change_tp=True)

    def _modify_order_price(self, account_id: str, order_id: str, new_price: float) -> None:
        mt5 = _mt5()
        self._send({"action": mt5.TRADE_ACTION_MODIFY, "order": int(order_id), "price": float(new_price)})


class MT5DataProvider(DataProvider):
    """Forex and CFD prices from the MetaTrader 5 terminal (bible section 5)."""

    name = "MT5"
    TIMEFRAMES = {"1m": "TIMEFRAME_M1", "5m": "TIMEFRAME_M5", "15m": "TIMEFRAME_M15", "1h": "TIMEFRAME_H1", "4h": "TIMEFRAME_H4", "1d": "TIMEFRAME_D1"}

    def __init__(self, suffix: str = ""):
        self.suffix = suffix

    async def fetch_history(self, provider_symbol, timeframe, start, end, extra):
        mt5 = _mt5()
        if mt5 is None or mt5.terminal_info() is None:
            raise ProviderError("MetaTrader 5 isn't connected. Connect an MT5 account first.")
        from datetime import datetime, timezone
        rates = await asyncio.to_thread(
            mt5.copy_rates_range, provider_symbol + self.suffix, getattr(mt5, self.TIMEFRAMES[timeframe]),
            datetime.fromtimestamp(start, tz=timezone.utc), datetime.fromtimestamp(end, tz=timezone.utc),
        )
        if rates is None:
            raise ProviderError(f"MetaTrader 5 has no history for {provider_symbol}.")
        return [Candle(int(r["time"]), float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]), float(r["tick_volume"])) for r in rates]

    async def stream(self, subscriptions, on_tick, on_candle, on_status):
        """MT5 has no push feed for Python, so ask for the latest price several times a second."""
        last_seen: dict[str, int] = {}
        connected = None
        while True:
            mt5 = _mt5()
            ok = mt5 is not None and mt5.terminal_info() is not None
            if ok != connected:
                on_status(self.name, "connected" if ok else "disconnected: MetaTrader 5 terminal not connected")
                connected = ok
            if ok:
                for symbol in {s for s, _ in subscriptions()}:
                    tick = mt5.symbol_info_tick(symbol + self.suffix)
                    if tick and tick.time_msc != last_seen.get(symbol):
                        last_seen[symbol] = tick.time_msc
                        on_tick(Tick(symbol=symbol, time=tick.time_msc / 1000, price=(tick.bid + tick.ask) / 2))
            await asyncio.sleep(0.2)
