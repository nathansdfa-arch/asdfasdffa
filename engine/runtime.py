"""The engine: builds every part and connects them together.

    data providers -> market data service -> message bus -> screens (WebSocket)
                                          -> paper broker (fills working orders)
                                          -> risk guard (recalculates accounts)
    scripts/buttons/automations -> order service -> risk guard -> broker
"""

import asyncio
import logging
import time
from pathlib import Path

from engine import paths
from engine.core.bus import MessageBus
from engine.core.markets import MarketCatalog
from engine.data.bybit import BybitProvider
from engine.data.cache import CandleCache
from engine.data.demo import DemoProvider
from engine.data.service import MarketDataService
from engine.execution.accounts import Account, AccountStore, RiskRules
from engine.execution.broker import BrokerConnector
from engine.execution.bybit_trading import BybitConnector
from engine.execution.mt5 import MT5Connector, MT5DataProvider, mt5_available
from engine.execution.orders import OrderService
from engine.execution.paper import PaperBroker
from engine.execution.rithmic import RithmicConnector
from engine.risk.guard import RiskGuard
from engine.risk.killswitch import KillSwitch
from engine.risk.profiles import ProfileStore
from engine.scripting.host import ScriptHost
from engine.scripting.store import ScriptStore
from engine.storage import database
from engine.storage.backups import Backups
from engine.storage.documents import DrawingStore, WorkspaceStore
from engine.storage.journal import Journal
from engine.storage.settings import SettingsStore
from engine.strategy.runner import Runner, RunStore

log = logging.getLogger(__name__)

RECONCILE_EVERY = 60     # seconds between broker balance checks (guard rule 8)


class Engine:
    def __init__(self, db_path: Path | None = None, clock=time.time, providers: dict | None = None):
        self.db_path = db_path or paths.database_path()
        self.schema_version = database.initialize(self.db_path)
        self.clock = clock
        self.started_at = clock()

        self.settings = SettingsStore(self.db_path)
        self.workspaces = WorkspaceStore(self.db_path)
        self.drawings = DrawingStore(self.db_path)
        self.journal = Journal(self.db_path)
        self.accounts = AccountStore(self.db_path)
        self.scripts = ScriptStore(self.db_path)
        self.scripts.seed_examples()
        self.profiles = ProfileStore()
        self.backups = Backups(self.db_path)
        self.bus = MessageBus()
        self.catalog = MarketCatalog()

        # Market data.
        self.cache = CandleCache(self.db_path)
        if providers is None:
            demo_info = {m.provider_symbol: {"tick_size": m.tick_size, "extra": m.extra} for m in self.catalog.all() if m.provider == "DEMO"}
            providers = {"DEMO": DemoProvider(demo_info), "BYBIT": BybitProvider()}
            if mt5_available():
                providers["MT5"] = MT5DataProvider()
        self.data = MarketDataService(self.catalog, self.cache, providers, self.bus, clock)
        self.data.stale_after = self.settings.get("stale_seconds")

        # Brokers. One shared paper broker; one connector per real broker account.
        self.paper = PaperBroker(
            self.catalog, self.data.last_price, clock,
            load_book=lambda a: self.journal.load_state("paper_books", a),
            save_book=lambda a, d: self.journal.save_state("paper_books", a, d),
        )
        self.connectors: dict[str, BrokerConnector] = {}

        self.guard = RiskGuard(self.accounts, self.broker_for, self.catalog, self.data.last_price, self.data.feed_status, self.journal, self.bus, clock)
        self.guard.profile_problem = self.profiles.problem
        self.paper._check_stamp = self.guard.check_stamp
        self.paper.add_listener(self._on_broker_event)
        self.orders = OrderService(self.accounts, self.guard, self.broker_for)
        self.kill_switch = KillSwitch(self.accounts, self.guard, self.orders, self.broker_for)
        self.host = ScriptHost(self.catalog)
        self.runner = Runner(self.scripts, self.data, self.orders, self.accounts, self.catalog, self.guard, self.bus, RunStore(self.db_path), clock)
        self.kill_switch.stoppers.append(self.runner.stop_all)

        self.bus.subscribe("tick", self._on_tick)
        self._tasks: list[asyncio.Task] = []
        self._ensure_default_accounts()
        for account in self.accounts.all():
            self._open(account)

    # ---- Accounts and brokers --------------------------------------------------

    def _ensure_default_accounts(self) -> None:
        if self.accounts.all():
            return
        self.accounts.create("Paper 25K", starting_balance=25000.0)
        example = self.profiles.get("illustrative_example")
        rules = self.profiles.rules_for(example, safety_buffer=100.0, current=RiskRules())
        self.accounts.create(
            "Prop practice (example rules)", starting_balance=25000.0, is_prop=True,
            profile_id="illustrative_example", rules=rules,
        )
        log.info("Created the default paper accounts")

    def _open(self, account: Account) -> None:
        if account.broker == "paper":
            self.paper.open_account(account.id, account.starting_balance)
        self.guard.state(account) if self.broker_for(account).connected else None

    def broker_for(self, account: Account) -> BrokerConnector:
        if account.broker == "paper" or not account.live_enabled:
            # Broker accounts trade on paper until live is deliberately switched on.
            if account.id not in self.paper.books:
                self.paper.open_account(account.id, account.starting_balance)
            return self.paper
        connector = self.connectors.get(account.id)
        if connector is None:
            makers = {"rithmic": RithmicConnector, "mt5": MT5Connector, "bybit": BybitConnector}
            connector = makers[account.broker](account.id, account.broker_settings, self.guard.check_stamp)
            connector.add_listener(self._on_broker_event)
            self.connectors[account.id] = connector
        return connector

    def connect_broker(self, account: Account) -> dict:
        """Try to log in to a real broker account (used when live is switched on, or by the Connect button)."""
        makers = {"rithmic": RithmicConnector, "mt5": MT5Connector, "bybit": BybitConnector}
        if account.broker not in makers:
            return {"ok": True, "status": "Paper accounts are always connected."}
        connector = self.connectors.get(account.id) or makers[account.broker](account.id, account.broker_settings, self.guard.check_stamp)
        connector.add_listener(self._on_broker_event)
        self.connectors[account.id] = connector
        ok = connector.connect() if hasattr(connector, "connect") else False
        return {"ok": ok, "status": getattr(connector, "status", "")}

    def create_account(self, name: str, **settings) -> Account:
        account = self.accounts.create(name, **settings)
        self._open(account)
        return account

    def reset_paper_account(self, account_id: str) -> None:
        account = self.accounts.get(account_id)
        self.paper.reset_account(account_id, account.starting_balance)
        self.guard.reset_account_state(account_id)
        self.guard.state(account)

    # ---- Events -------------------------------------------------------------------

    def _on_tick(self, topic: str, tick: dict) -> None:
        self.paper.on_price(tick["symbol"], tick["price"])
        self.guard.on_price(tick["symbol"])

    def _on_broker_event(self, kind: str, details: dict) -> None:
        if kind == "fill":
            self.journal.record_fill(details)
            self.guard.on_fill(details)
        self.bus.publish(kind, details)

    # ---- Running ---------------------------------------------------------------------

    async def start(self) -> None:
        await self.data.start()
        await self.runner.start_scheduler()
        self._tasks.append(asyncio.create_task(self._housekeeping(), name="housekeeping"))
        asyncio.get_running_loop().run_in_executor(None, self.host.warm_up)
        log.info("Engine started")

    async def _housekeeping(self) -> None:
        """Once a minute: balance checks (rule 8), new trading days, and the daily backup."""
        while True:
            await asyncio.sleep(RECONCILE_EVERY)
            try:
                self.guard.reconcile_balances()
                for account in self.accounts.all():
                    if self.broker_for(account).connected:
                        self.guard.evaluate(account)
                await asyncio.to_thread(self.backups.make_if_due)
            except Exception:
                log.exception("Housekeeping failed")

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.data.stop()
        await self.runner.close()
        self.host.close()
        log.info("Engine stopped")
