"""The paper broker: a simulated broker that trades with pretend money.

It follows the shared fill model (engine/execution/fill_model.py) and keeps
a book per paper account: balance, positions and working orders. Books are
saved to the database after every change, so a restart keeps them.

Each position has at most one stop loss and one take profit. They are real
working orders in the book ("held at the broker"), sized to the position,
and cancel each other: when one fills, the other is cancelled.

Market orders fill straight away at the latest live price plus slippage. If
no price has arrived yet (feed down), they wait for the next price.
"""

import itertools
import logging
from dataclasses import dataclass, field
from typing import Callable

from engine.core.markets import MarketCatalog
from engine.core.models import AccountSnapshot, Order, OrderRequest, OrderStatus, OrderType, Position, Side
from engine.execution import fill_model
from engine.execution.broker import BrokerConnector, OrderRefused

log = logging.getLogger(__name__)


@dataclass
class PaperBook:
    balance: float
    positions: dict[str, Position] = field(default_factory=dict)
    orders: dict[str, Order] = field(default_factory=dict)          # working orders only
    attached: dict[str, dict] = field(default_factory=dict)         # entry order id -> {"stop_loss", "take_profit"}

    def to_dict(self) -> dict:
        return {
            "balance": self.balance,
            "positions": {s: p.to_dict() for s, p in self.positions.items()},
            "orders": {i: o.to_dict() for i, o in self.orders.items()},
            "attached": self.attached,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PaperBook":
        book = cls(balance=data["balance"], attached=data.get("attached", {}))
        for symbol, p in data.get("positions", {}).items():
            book.positions[symbol] = Position(**p)
        for order_id, o in data.get("orders", {}).items():
            o = dict(o)
            o["side"] = Side(o["side"])
            o["order_type"] = OrderType(o["order_type"])
            o["status"] = OrderStatus(o["status"])
            book.orders[order_id] = Order(**o)
        return book


class PaperBroker(BrokerConnector):
    name = "paper"
    supports_broker_stops = True
    reports_fills = True

    def __init__(
        self,
        catalog: MarketCatalog,
        last_price: Callable[[str], float | None],
        clock: Callable[[], float],
        check_stamp=None,
        load_book: Callable[[str], dict | None] | None = None,
        save_book: Callable[[str, dict], None] | None = None,
    ):
        super().__init__(check_stamp)
        self.catalog = catalog
        self.last_price = last_price
        self.clock = clock
        self._load_book = load_book or (lambda account_id: None)
        self._save_book = save_book or (lambda account_id, data: None)
        self.books: dict[str, PaperBook] = {}
        self._ids = itertools.count(1)

    # ---- Books --------------------------------------------------------------

    def open_account(self, account_id: str, starting_balance: float) -> None:
        """Load a paper account's book, or start a new one."""
        saved = self._load_book(account_id)
        self.books[account_id] = PaperBook.from_dict(saved) if saved else PaperBook(balance=starting_balance)
        if not saved:
            self._save(account_id)

    def reset_account(self, account_id: str, starting_balance: float) -> None:
        self.books[account_id] = PaperBook(balance=starting_balance)
        self._save(account_id)
        self._emit("account", {"account_id": account_id})

    def _book(self, account_id: str) -> PaperBook:
        if account_id not in self.books:
            raise OrderRefused(f"Paper account '{account_id}' is not open.")
        return self.books[account_id]

    def _save(self, account_id: str) -> None:
        self._save_book(account_id, self.books[account_id].to_dict())

    def _new_id(self) -> str:
        return f"P{int(self.clock() * 1000)}-{next(self._ids)}"

    # ---- What the interface asks for ---------------------------------------

    @property
    def connected(self) -> bool:
        return True

    def snapshot(self, account_id: str) -> AccountSnapshot:
        book = self._book(account_id)
        open_pnl = 0.0
        for symbol, position in book.positions.items():
            price = self.last_price(symbol)
            if price is not None and not position.is_flat:
                market = self.catalog.get(symbol)
                open_pnl += (price - position.average_price) * position.quantity * market.point_value
        return AccountSnapshot(account_id=account_id, balance=book.balance, open_pnl=open_pnl)

    def positions(self, account_id: str) -> list[Position]:
        return [p for p in self._book(account_id).positions.values() if not p.is_flat]

    def working_orders(self, account_id: str) -> list[Order]:
        return list(self._book(account_id).orders.values())

    def _place(self, request: OrderRequest) -> Order:
        book = self._book(request.account_id)
        market = self.catalog.get(request.symbol)
        if request.order_type is not OrderType.MARKET and request.price is None:
            raise OrderRefused("Limit and stop orders need a price.")
        order = Order(
            id=self._new_id(),
            account_id=request.account_id,
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            order_type=request.order_type,
            price=market.round_price(request.price) if request.price is not None else None,
            status=OrderStatus.WORKING,
            created_at=self.clock(),
            role="close" if request.reduce_only else "entry",
            source=request.source,
        )
        book.orders[order.id] = order
        if request.stop_loss is not None or request.take_profit is not None:
            book.attached[order.id] = {"stop_loss": request.stop_loss, "take_profit": request.take_profit}
        self._emit("order", order.to_dict())
        if order.order_type is OrderType.MARKET:
            price = self.last_price(order.symbol)
            if price is not None:
                self._fill(book, order, fill_model.market_fill_price(order.side, price, market))
        self._save(request.account_id)
        return order

    def _cancel(self, account_id: str, order_id: str) -> None:
        book = self._book(account_id)
        order = book.orders.pop(order_id, None)
        if order is None:
            raise OrderRefused("That order is no longer working.")
        order.status = OrderStatus.CANCELLED
        book.attached.pop(order_id, None)
        self._save(account_id)
        self._emit("order", order.to_dict())

    def _modify_stop(self, account_id: str, symbol: str, new_stop: float) -> None:
        book = self._book(account_id)
        position = book.positions.get(symbol)
        if position is None or position.is_flat:
            raise OrderRefused("There is no open position to protect.")
        market = self.catalog.get(symbol)
        stop = self._child(book, symbol, "stop_loss")
        if stop is None:
            self._set_child(book, position, "stop_loss", OrderType.STOP, new_stop)
        else:
            stop.price = market.round_price(new_stop)
            self._emit("order", stop.to_dict())
        self._save(account_id)

    def _modify_target(self, account_id: str, symbol: str, new_target: float | None) -> None:
        book = self._book(account_id)
        position = book.positions.get(symbol)
        target = self._child(book, symbol, "take_profit")
        if new_target is None:
            if target:
                book.orders.pop(target.id)
                target.status = OrderStatus.CANCELLED
                self._emit("order", target.to_dict())
        elif position is None or position.is_flat:
            raise OrderRefused("There is no open position for a target.")
        elif target is None:
            self._set_child(book, position, "take_profit", OrderType.LIMIT, new_target)
        else:
            target.price = self.catalog.get(symbol).round_price(new_target)
            self._emit("order", target.to_dict())
        self._save(account_id)

    def _modify_order_price(self, account_id: str, order_id: str, new_price: float) -> None:
        book = self._book(account_id)
        order = book.orders.get(order_id)
        if order is None or order.order_type is OrderType.MARKET:
            raise OrderRefused("Only working limit or stop orders can be moved.")
        order.price = self.catalog.get(order.symbol).round_price(new_price)
        self._save(account_id)
        self._emit("order", order.to_dict())

    # ---- Prices and fills ----------------------------------------------------

    def on_price(self, symbol: str, price: float) -> None:
        """A new live price: fill any working orders it reaches."""
        market = self.catalog.markets.get(symbol)
        if market is None:
            return
        for account_id, book in self.books.items():
            changed = False
            # Stops are checked before targets, so on a wild price the loss is assumed (cautious).
            orders = sorted(
                (o for o in book.orders.values() if o.symbol == symbol),
                key=lambda o: (o.role != "stop_loss", o.created_at),
            )
            for order in orders:
                if order.id not in book.orders:
                    continue   # cancelled by an earlier fill in this loop
                fill_price = fill_model.fill_on_tick(order.order_type, order.side, order.price, price, market)
                if fill_price is not None:
                    self._fill(book, order, fill_price)
                    changed = True
            if changed:
                self._save(account_id)

    def _fill(self, book: PaperBook, order: Order, price: float) -> None:
        market = self.catalog.get(order.symbol)
        position = book.positions.setdefault(order.symbol, Position(account_id=order.account_id, symbol=order.symbol))
        quantity = order.quantity
        if order.role != "entry":
            # Closing orders, stops and targets can only shrink the position.
            available = abs(position.quantity)
            if available < 1e-12 or (position.quantity > 0) == (order.side is Side.BUY):
                book.orders.pop(order.id, None)
                order.status = OrderStatus.CANCELLED
                self._emit("order", order.to_dict())
                return
            quantity = min(quantity, available)

        signed = quantity * order.side.sign
        fee = market.fee(quantity, price)
        position.quantity, position.average_price, realized = fill_model.apply_fill(
            position.quantity, position.average_price, signed, price, market.point_value
        )
        position.realized_pnl += realized
        book.balance += realized - fee

        order.status = OrderStatus.FILLED
        order.filled_price = price
        order.filled_at = self.clock()
        order.quantity = quantity
        book.orders.pop(order.id, None)

        fill = {
            "account_id": order.account_id, "order_id": order.id, "symbol": order.symbol, "side": order.side.value,
            "quantity": quantity, "price": price, "fee": fee, "realized": realized, "role": order.role,
            "source": order.source, "time": self.clock(),
        }
        self._emit("fill", fill)
        self._emit("order", order.to_dict())

        attached = book.attached.pop(order.id, None)
        if position.is_flat:
            self._cancel_children(book, order.symbol)
        else:
            if attached:
                if attached.get("stop_loss") is not None:
                    self._set_child(book, position, "stop_loss", OrderType.STOP, attached["stop_loss"])
                if attached.get("take_profit") is not None:
                    self._set_child(book, position, "take_profit", OrderType.LIMIT, attached["take_profit"])
            self._resize_children(book, position)
        self._emit("position", position.to_dict())

    # ---- Stop loss and take profit children ---------------------------------

    def _child(self, book: PaperBook, symbol: str, role: str) -> Order | None:
        return next((o for o in book.orders.values() if o.symbol == symbol and o.role == role), None)

    def _set_child(self, book: PaperBook, position: Position, role: str, order_type: OrderType, price: float) -> None:
        existing = self._child(book, position.symbol, role)
        if existing:
            book.orders.pop(existing.id)
        market = self.catalog.get(position.symbol)
        child = Order(
            id=self._new_id(),
            account_id=position.account_id,
            symbol=position.symbol,
            side=Side.SELL if position.quantity > 0 else Side.BUY,
            quantity=abs(position.quantity),
            order_type=order_type,
            price=market.round_price(price),
            status=OrderStatus.WORKING,
            created_at=self.clock(),
            role=role,
            source="protective",
        )
        book.orders[child.id] = child
        self._emit("order", child.to_dict())

    def _resize_children(self, book: PaperBook, position: Position) -> None:
        for order in list(book.orders.values()):
            if order.symbol == position.symbol and order.role in ("stop_loss", "take_profit"):
                order.quantity = abs(position.quantity)
                order.side = Side.SELL if position.quantity > 0 else Side.BUY

    def _cancel_children(self, book: PaperBook, symbol: str) -> None:
        for order in list(book.orders.values()):
            if order.symbol == symbol and order.role in ("stop_loss", "take_profit"):
                book.orders.pop(order.id)
                order.status = OrderStatus.CANCELLED
                self._emit("order", order.to_dict())
