"""The BrokerConnector interface: what every broker connection must do.

Guard rule 1, "one door": a connector refuses any order, change or
cancellation that does not carry a valid approval stamp from the risk guard.
The connector is handed the guard's stamp checker when it is created; it
has no way to make its own stamps.
"""

from abc import ABC, abstractmethod
from typing import Callable

from engine.core.models import AccountSnapshot, Order, OrderRequest, Position

StampChecker = Callable[[str, str, str], bool]   # action, fingerprint, stamp -> valid?


class OrderRefused(Exception):
    """The connector refused the order. The message is plain English."""


class NotConfigured(Exception):
    """The connector cannot be used yet, for example because credentials or approval are missing."""


def request_fingerprint(request: OrderRequest) -> str:
    """A short text that identifies exactly what was approved, so a stamp can't be reused for something else."""
    return "|".join(
        str(x)
        for x in (
            request.account_id, request.symbol, request.side.value, request.quantity, request.order_type.value,
            request.price, request.stop_loss, request.take_profit, request.reduce_only,
        )
    )


class BrokerConnector(ABC):
    name = "base"
    # Guard rule 7: can this broker hold a real stop loss order attached to a position?
    supports_broker_stops = True
    # Guard rule 8 needs every fill reported as it happens. Only the paper broker does so far.
    reports_fills = False

    def __init__(self, check_stamp: StampChecker | None = None):
        # Without the guard's checker, every stamp is invalid and every order is refused.
        self._check_stamp = check_stamp or (lambda action, fingerprint, stamp: False)
        self._listeners: list[Callable[[str, dict], None]] = []

    # ---- The one door -------------------------------------------------------

    def _require_stamp(self, action: str, fingerprint: str, stamp: str | None) -> None:
        if not stamp or not self._check_stamp(action, fingerprint, stamp):
            raise OrderRefused("Refused: this order has no valid approval from the risk guard.")

    def place_order(self, request: OrderRequest, stamp: str | None) -> Order:
        self._require_stamp("place", request_fingerprint(request), stamp)
        return self._place(request)

    def cancel_order(self, account_id: str, order_id: str, stamp: str | None) -> None:
        self._require_stamp("cancel", f"{account_id}|{order_id}", stamp)
        self._cancel(account_id, order_id)

    def modify_stop(self, account_id: str, symbol: str, new_stop: float, stamp: str | None) -> None:
        self._require_stamp("modify_stop", f"{account_id}|{symbol}|{new_stop}", stamp)
        self._modify_stop(account_id, symbol, new_stop)

    def modify_target(self, account_id: str, symbol: str, new_target: float | None, stamp: str | None) -> None:
        self._require_stamp("modify_target", f"{account_id}|{symbol}|{new_target}", stamp)
        self._modify_target(account_id, symbol, new_target)

    def modify_order_price(self, account_id: str, order_id: str, new_price: float, stamp: str | None) -> None:
        self._require_stamp("modify_price", f"{account_id}|{order_id}|{new_price}", stamp)
        self._modify_order_price(account_id, order_id, new_price)

    # ---- Events -------------------------------------------------------------

    def add_listener(self, listener: Callable[[str, dict], None]) -> None:
        """Called with ("fill" | "order" | "position" | "account", details)."""
        self._listeners.append(listener)

    def _emit(self, kind: str, details: dict) -> None:
        for listener in list(self._listeners):
            listener(kind, details)

    # ---- What each broker implements ---------------------------------------

    @property
    @abstractmethod
    def connected(self) -> bool: ...

    @abstractmethod
    def snapshot(self, account_id: str) -> AccountSnapshot: ...

    @abstractmethod
    def positions(self, account_id: str) -> list[Position]: ...

    @abstractmethod
    def working_orders(self, account_id: str) -> list[Order]: ...

    @abstractmethod
    def _place(self, request: OrderRequest) -> Order: ...

    @abstractmethod
    def _cancel(self, account_id: str, order_id: str) -> None: ...

    @abstractmethod
    def _modify_stop(self, account_id: str, symbol: str, new_stop: float) -> None: ...

    def _modify_target(self, account_id: str, symbol: str, new_target: float | None) -> None:
        raise OrderRefused(f"{self.name} cannot change targets yet.")

    def _modify_order_price(self, account_id: str, order_id: str, new_price: float) -> None:
        raise OrderRefused(f"{self.name} cannot move working orders yet.")

    def stop_price(self, account_id: str, symbol: str) -> float | None:
        """The price of the working stop loss protecting this position, if any."""
        for order in self.working_orders(account_id):
            if order.symbol == symbol and order.role == "stop_loss":
                return order.price
        return None

    def target_price(self, account_id: str, symbol: str) -> float | None:
        for order in self.working_orders(account_id):
            if order.symbol == symbol and order.role == "take_profit":
                return order.price
        return None

    def position(self, account_id: str, symbol: str) -> Position:
        for position in self.positions(account_id):
            if position.symbol == symbol:
                return position
        return Position(account_id=account_id, symbol=symbol)

    async def reconcile(self, account_id: str) -> dict:
        """After a reconnect: fetch positions and orders from the broker before doing anything else."""
        return {
            "positions": [p.to_dict() for p in self.positions(account_id)],
            "orders": [o.to_dict() for o in self.working_orders(account_id)],
        }
