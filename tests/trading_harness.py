"""A small trading setup for tests: paper broker, risk guard and order service,
with prices and time fully controlled by the test."""

from engine.core.bus import MessageBus
from engine.core.clock import FakeClock
from engine.core.markets import MarketCatalog
from engine.core.models import OrderRequest, OrderType, Side
from engine.execution.accounts import AccountStore, RiskRules
from engine.execution.orders import OrderService
from engine.execution.paper import PaperBroker
from engine.risk.guard import RiskGuard
from engine.risk.killswitch import KillSwitch
from engine.storage import database
from engine.storage.journal import Journal

# 2026-03-04 15:00 UTC, a Wednesday (10:00 in New York).
START = 1772636400.0


class Harness:
    def __init__(self, tmp_path):
        db = tmp_path / "test.db"
        database.initialize(db)
        self.clock = FakeClock(START)
        self.bus = MessageBus()
        self.events = []
        self.bus.subscribe("*", lambda topic, msg: self.events.append((topic, msg)))
        self.catalog = MarketCatalog()
        self.journal = Journal(db)
        self.accounts = AccountStore(db)
        self.prices: dict[str, float] = {}
        self.feeds: dict[str, str] = {}
        self.broker = PaperBroker(
            self.catalog, self.prices.get, self.clock.now,
            load_book=lambda a: self.journal.load_state("paper_books", a),
            save_book=lambda a, d: self.journal.save_state("paper_books", a, d),
        )
        self.guard = RiskGuard(
            self.accounts, lambda account: self.broker, self.catalog, self.prices.get,
            lambda s: self.feeds.get(s, "ok" if s in self.prices else "waiting"), self.journal, self.bus, self.clock.now,
        )
        self.broker._check_stamp = self.guard.check_stamp
        self.broker.add_listener(self._on_broker_event)
        self.orders = OrderService(self.accounts, self.guard, lambda account: self.broker)
        self.kill = KillSwitch(self.accounts, self.guard, self.orders, lambda account: self.broker)

    def _on_broker_event(self, kind, details):
        if kind == "fill":
            self.journal.record_fill(details)
            self.guard.on_fill(details)

    def account(self, name="Test", balance=25000.0, **rules):
        is_prop = rules.pop("is_prop", False)
        account = self.accounts.create(name, starting_balance=balance, is_prop=is_prop, rules=RiskRules(**rules))
        self.broker.open_account(account.id, balance)
        self.guard.state(account)      # the engine does this for every account at startup
        return account

    def price(self, symbol, price):
        self.prices[symbol] = price
        self.broker.on_price(symbol, price)
        self.guard.on_price(symbol)

    def order(self, account, symbol="DEMO:ES", side="buy", qty=1, stop=None, target=None, kind="market", price=None, source="manual"):
        request = OrderRequest(
            account_id=account.id, symbol=symbol, side=Side(side), quantity=qty,
            order_type=OrderType(kind), price=price, stop_loss=stop, take_profit=target, source=source,
        )
        return self.orders.submit(request)


def prop_rules(**overrides):
    """The bible's illustrative example: 25,000 account, 1,000 intraday trailing drawdown locking at 25,000, 100 buffer."""
    rules = dict(drawdown_amount=1000, drawdown_method="intraday", drawdown_lock=25000, safety_buffer=100, is_prop=True)
    rules.update(overrides)
    return rules
