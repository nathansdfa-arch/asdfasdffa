"""Trading accounts and their risk rules.

An account is either a paper account (simulated money) or a broker account
(Rithmic, MetaTrader 5, Bybit). A prop firm account is an ordinary account
with a prop firm rule profile attached (bible section 10).

Safety: every account starts in paper mode. A broker account can only trade
live after the owner deliberately switches it on with a typed confirmation
(bible section 8), and paper accounts can never be live.
"""

import json
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from engine.storage.database import connect, utc_now


@dataclass
class RiskRules:
    """The limits the risk guard enforces for one account. None means "no limit"."""

    max_daily_loss: float | None = None          # money; loss today including open trades
    drawdown_amount: float | None = None         # money; size of the (trailing) drawdown
    drawdown_method: str = "intraday"            # intraday, end_of_day, static
    drawdown_lock: float | None = None           # floor stops rising here
    max_position_size: float | None = None       # contracts/lots in one symbol
    max_total_quantity: float | None = None      # contracts/lots across all symbols
    allowed_hours: str | None = None             # "08:30-15:00" in hours_timezone; None = any time
    hours_timezone: str = "America/New_York"
    daily_trade_limit: int | None = None         # new positions opened per trading day
    require_stop_loss: bool = False              # every new order needs a stop (always on for prop accounts)
    safety_buffer: float = 0.0                   # money kept between the guard's limit and the firm's
    auto_flatten_at_limit: bool = False          # at 100% used: close everything and halt this account
    reset_time: str = "17:00"                    # when the trading day starts and ends
    reset_timezone: str = "America/New_York"
    duplicate_window_seconds: float = 2.0        # same symbol, side and size this soon = duplicate
    max_orders_per_minute_per_script: int = 10   # more than this pauses the script
    balance_tolerance: float = 1.0               # allowed gap between our balance and the broker's
    profit_target: float | None = None           # evaluation target (prop simulator)

    @classmethod
    def from_dict(cls, data: dict) -> "RiskRules":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Account:
    id: str
    name: str
    broker: str = "paper"                # paper, rithmic, mt5, bybit
    starting_balance: float = 25000.0
    currency: str = "USD"
    is_prop: bool = False
    profile_id: str | None = None        # prop firm rule profile (config/prop_firms.json)
    live_enabled: bool = False           # only ever True for broker accounts after a typed confirmation
    live_enabled_at: str | None = None
    broker_settings: dict = field(default_factory=dict)   # e.g. server name; never passwords (those go to Windows Credential Manager)
    rules: RiskRules = field(default_factory=RiskRules)

    @property
    def mode(self) -> str:
        """PAPER or LIVE, as shown on every badge."""
        return "LIVE" if self.live_enabled and self.broker != "paper" else "PAPER"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["mode"] = self.mode
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Account":
        data = dict(data)
        data.pop("mode", None)
        rules = RiskRules.from_dict(data.pop("rules", {}) or {})
        known = {f.name for f in fields(cls)}
        return cls(rules=rules, **{k: v for k, v in data.items() if k in known})


class AccountStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._cache: dict[str, Account] | None = None

    def all(self) -> list[Account]:
        if self._cache is None:
            with connect(self.db_path) as conn:
                rows = conn.execute("SELECT config FROM accounts ORDER BY created_at").fetchall()
            self._cache = {}
            for row in rows:
                account = Account.from_dict(json.loads(row["config"]))
                self._cache[account.id] = account
        return list(self._cache.values())

    def get(self, account_id: str) -> Account:
        for account in self.all():
            if account.id == account_id:
                return account
        raise KeyError(f"There is no account '{account_id}'.")

    def save(self, account: Account) -> Account:
        if account.broker == "paper":
            account.live_enabled = False   # paper accounts can never be live
        if account.is_prop:
            account.rules.require_stop_loss = True   # guard rule 4
        with connect(self.db_path) as conn:
            existing = conn.execute("SELECT created_at FROM accounts WHERE id = ?", (account.id,)).fetchone()
            conn.execute(
                "INSERT OR REPLACE INTO accounts (id, config, created_at) VALUES (?, ?, ?)",
                (account.id, json.dumps(account.to_dict()), existing["created_at"] if existing else utc_now()),
            )
        self._cache = None
        return account

    def create(self, name: str, **settings) -> Account:
        rules = settings.pop("rules", None)
        account = Account(id=uuid.uuid4().hex[:10], name=name, **settings)
        if isinstance(rules, RiskRules):
            account.rules = rules
        elif isinstance(rules, dict):
            account.rules = RiskRules.from_dict(rules)
        return self.save(account)

    def delete(self, account_id: str) -> None:
        with connect(self.db_path) as conn:
            for table, column in (("accounts", "id"), ("account_state", "account_id"), ("paper_books", "account_id")):
                conn.execute(f"DELETE FROM {table} WHERE {column} = ?", (account_id,))
        self._cache = None
