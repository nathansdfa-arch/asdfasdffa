"""The risk guard (bible section 9). Every order from any script, button or
automation must pass through here. It is the only route to a broker.

The eight guard rules, and where each lives in this file:

 1. One door.        Approved orders get a signed, single-use "stamp" (issue_stamp).
                     Connectors refuse anything without a valid stamp (check_stamp).
 2. Let the owner out. Orders that reduce risk are always allowed (_classify).
 3. Fail closed.     If the numbers can't be worked out, new risk is blocked (_preflight,
                     and the try/except around every review).
 4. Worst case.      New orders on limited accounts need a stop; the loss if every stop
                     is hit must still fit inside every limit (_worst_case_check).
 5. Safety buffer.   The guard's own limits are the firm's limits tightened by the
                     owner's buffer (numbers()).
 6. Thresholds.      Warn at 70% used, block at 100%, optionally close everything
                     (_check_thresholds).
 7. Stops at broker. Brokers that can't hold a real stop order get no new orders (_preflight).
 8. Firm's number wins. Our balance is compared with the broker's after every fill
                     and once a minute (reconcile_balances).

Every decision is written to the guard log with the rule, numbers and result.
"""

import hashlib
import hmac
import logging
import secrets
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from engine.core.bus import MessageBus
from engine.core.markets import MarketCatalog
from engine.core.models import OrderRequest, OrderType, Side
from engine.execution.accounts import Account, AccountStore
from engine.execution.broker import BrokerConnector, request_fingerprint
from engine.risk.drawdown import DrawdownConfig, DrawdownState, TrailingDrawdown
from engine.storage.journal import Journal

log = logging.getLogger(__name__)

WARN_AT = 0.70
BLOCK_AT = 1.00
STAMP_LIFETIME_SECONDS = 10


@dataclass
class Decision:
    approved: bool
    rule: str                 # which rule decided, e.g. "Rule 4: worst case"
    reason: str               # plain English, shown to the owner
    numbers: dict = field(default_factory=dict)
    stamp: str | None = None
    reduces_risk: bool = False

    def to_dict(self) -> dict:
        data = asdict(self)
        data.pop("stamp")
        return data


@dataclass
class AccountState:
    trading_day: str = ""
    day_start_balance: float | None = None
    trades_today: int = 0
    drawdown: dict | None = None          # DrawdownState as a dict
    warned: bool = False                  # 70% warning already sent today
    limit_hit: bool = False               # 100% reached today: new risk blocked
    halted: bool = False                  # account halted (auto-flatten or failed) until the owner resumes it
    halt_reason: str = ""
    failed: bool = False                  # drawdown floor touched
    expected_balance: float | None = None  # rule 8: our own running balance
    balance_mismatch: bool = False
    days_traded: list = field(default_factory=list)   # trading days with at least one fill (evaluations)


def trading_day_for(unix_time: float, reset_time: str, reset_timezone: str) -> str:
    """Which trading day a moment belongs to. A day starts at the reset time and
    is named after the calendar day it mostly covers, so with a 17:00 reset,
    Monday 18:00 belongs to Tuesday's trading day (the futures convention)."""
    local = datetime.fromtimestamp(unix_time, tz=timezone.utc).astimezone(ZoneInfo(reset_timezone))
    hours, minutes = (int(x) for x in reset_time.split(":"))
    reset_minutes = hours * 60 + minutes
    day = local.date()
    if reset_minutes > 0 and local.hour * 60 + local.minute >= reset_minutes:
        day = day + timedelta(days=1)
    return day.isoformat()


def within_hours(unix_time: float, hours_text: str, tz_name: str) -> bool:
    local = datetime.fromtimestamp(unix_time, tz=timezone.utc).astimezone(ZoneInfo(tz_name))
    start_text, end_text = hours_text.split("-")
    start = int(start_text[:2]) * 60 + int(start_text[3:5])
    end = int(end_text[:2]) * 60 + int(end_text[3:5])
    now = local.hour * 60 + local.minute
    return start <= now < end if start < end else (now >= start or now < end)


class RiskGuard:
    def __init__(
        self,
        accounts: AccountStore,
        broker_for: Callable[[Account], BrokerConnector],
        catalog: MarketCatalog,
        last_price: Callable[[str], float | None],
        feed_status: Callable[[str], str],
        journal: Journal,
        bus: MessageBus,
        clock: Callable[[], float] = time.time,
    ):
        self.accounts = accounts
        self.broker_for = broker_for
        self.catalog = catalog
        self.last_price = last_price
        self.feed_status = feed_status
        self.journal = journal
        self.bus = bus
        self.clock = clock

        self._secret = secrets.token_bytes(32)   # only the guard knows it, so only the guard can stamp
        self._used_nonces: dict[str, float] = {}
        self._states: dict[str, AccountState] = {}
        self._trackers: dict[str, TrailingDrawdown] = {}
        self._recent: deque = deque(maxlen=500)               # (time, account, symbol, side, qty)
        self._source_times: dict[str, deque] = {}             # script/automation -> order times
        self.paused_sources: set[str] = set()
        self._pending: dict[str, OrderRequest] = {}           # working entry orders the guard approved
        saved = journal.load_state("account_state", "__kill_switch__") or {}
        self.trading_halted: bool = bool(saved.get("halted", False))   # kill switch: everything halted
        # Set by other parts of the engine:
        self.flatten_account: Callable[[str, str], None] = lambda account_id, reason: None
        self.profile_problem: Callable[[Account], str | None] = lambda account: None

    # ======================================================================
    # Rule 1: approval stamps
    # ======================================================================

    def issue_stamp(self, action: str, fingerprint: str) -> str:
        nonce = secrets.token_hex(8)
        expires = f"{self.clock() + STAMP_LIFETIME_SECONDS:.3f}"
        signature = hmac.new(self._secret, f"{action}|{fingerprint}|{nonce}|{expires}".encode(), hashlib.sha256).hexdigest()
        return f"{nonce}:{expires}:{signature}"

    def check_stamp(self, action: str, fingerprint: str, stamp: str) -> bool:
        """Connectors call this. A stamp is valid once, for exactly the approved order, for 10 seconds."""
        try:
            nonce, expires, signature = stamp.split(":")
        except (ValueError, AttributeError):
            return False
        expected = hmac.new(self._secret, f"{action}|{fingerprint}|{nonce}|{expires}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return False
        now = self.clock()
        if now > float(expires) or nonce in self._used_nonces:
            return False
        self._used_nonces[nonce] = now
        for old, used_at in list(self._used_nonces.items()):
            if now - used_at > 60:
                del self._used_nonces[old]
        return True

    # ======================================================================
    # Account state and numbers
    # ======================================================================

    def state(self, account: Account) -> AccountState:
        state = self._states.get(account.id)
        if state is None:
            saved = self.journal.load_state("account_state", account.id)
            state = AccountState(**saved) if saved else AccountState()
            self._states[account.id] = state
        self._roll_day_if_needed(account, state)
        return state

    def _save_state(self, account_id: str) -> None:
        if account_id in self._states:
            self.journal.save_state("account_state", account_id, asdict(self._states[account_id]))

    def tracker(self, account: Account) -> TrailingDrawdown | None:
        rules = account.rules
        if rules.drawdown_amount is None:
            return None
        tracker = self._trackers.get(account.id)
        config = DrawdownConfig(account.starting_balance, rules.drawdown_amount, rules.drawdown_method, rules.drawdown_lock)
        if tracker is None or tracker.config != config:
            state = self._states.get(account.id)
            saved = DrawdownState(**state.drawdown) if state and state.drawdown and tracker is None else None
            tracker = TrailingDrawdown(config, saved)
            self._trackers[account.id] = tracker
        return tracker

    def _roll_day_if_needed(self, account: Account, state: AccountState) -> None:
        today = trading_day_for(self.clock(), account.rules.reset_time, account.rules.reset_timezone)
        if state.trading_day == today:
            return
        broker = self.broker_for(account)
        balance = broker.snapshot(account.id).balance if broker.connected else state.day_start_balance
        first_day = state.trading_day == ""
        state.trading_day = today
        state.day_start_balance = balance if balance is not None else account.starting_balance
        state.trades_today = 0
        state.warned = False
        state.limit_hit = False
        if state.expected_balance is None:
            state.expected_balance = state.day_start_balance
        tracker = self.tracker(account)
        if tracker and not first_day:
            tracker.on_daily_reset(state.day_start_balance)
        if tracker:
            state.drawdown = tracker.state.to_dict()
        self._save_state(account.id)
        if not first_day:
            log.info("New trading day %s for account %s", today, account.name)

    def numbers(self, account: Account) -> dict:
        """Everything the guard knows about an account's money, for decisions and the status strip."""
        broker = self.broker_for(account)
        state = self.state(account)
        rules = account.rules
        snap = broker.snapshot(account.id)
        equity = snap.equity
        buffer = rules.safety_buffer or 0.0
        loss_today = max(0.0, (state.day_start_balance or snap.balance) - equity)
        result = {
            "balance": round(snap.balance, 2),
            "open_pnl": round(snap.open_pnl, 2),
            "equity": round(equity, 2),
            "day_start_balance": state.day_start_balance,
            "loss_today": round(loss_today, 2),
            "safety_buffer": buffer,
            "trades_today": state.trades_today,
            "used": 0.0,
        }
        used = []
        if rules.max_daily_loss:
            guard_daily = rules.max_daily_loss - buffer
            result["daily_limit"] = rules.max_daily_loss
            result["guard_daily_limit"] = guard_daily
            result["daily_room_left"] = round(guard_daily - loss_today, 2)
            used.append(loss_today / guard_daily if guard_daily > 0 else 1.0)
        tracker = self.tracker(account)
        if tracker:
            floor = tracker.state.floor
            guard_floor = floor + buffer
            total_room = rules.drawdown_amount - buffer
            room = equity - guard_floor
            result.update({
                "high_water_mark": round(tracker.state.high_water_mark, 2),
                "floor": round(floor, 2),
                "guard_floor": round(guard_floor, 2),
                "room_left": round(equity - floor, 2),
                "guard_room_left": round(room, 2),
                "floor_locked": tracker.state.locked,
                "failed": tracker.state.failed,
            })
            used.append(max(0.0, 1 - room / total_room) if total_room > 0 else 1.0)
        if used:
            result["used"] = round(max(used), 4)
        result["warning"] = result["used"] >= WARN_AT
        result["blocked"] = result["used"] >= BLOCK_AT or state.limit_hit or state.halted or state.failed or self.trading_halted
        result["halted"] = state.halted
        result["halt_reason"] = state.halt_reason
        result["failed"] = state.failed
        result["balance_mismatch"] = state.balance_mismatch
        result["trading_halted"] = self.trading_halted
        result["mode"] = account.mode
        if rules.profit_target:
            result["profit_target"] = rules.profit_target
            result["profit_so_far"] = round(equity - account.starting_balance, 2)
            result["days_traded"] = len(state.days_traded)
        return result

    # ======================================================================
    # Reviews
    # ======================================================================

    def review_order(self, request: OrderRequest) -> Decision:
        """Approve or block a new order. Anything unexpected blocks it (rule 3)."""
        try:
            decision = self._review_order(request)
        except Exception as problem:
            log.exception("Risk guard could not check an order")
            decision = Decision(False, "Rule 3: fail closed", f"The guard could not check this order safely ({problem}), so it was blocked.")
        if decision.approved:
            decision.stamp = self.issue_stamp("place", request_fingerprint(request))
        self._log("place", request.account_id, request.symbol, decision, request.source)
        return decision

    def _review_order(self, request: OrderRequest) -> Decision:
        account = self.accounts.get(request.account_id)
        market = self.catalog.get(request.symbol)
        broker = self.broker_for(account)
        if request.quantity <= 0:
            return Decision(False, "Order check", "The quantity must be more than zero.")
        steps = request.quantity / market.quantity_step
        if abs(steps - round(steps)) > 1e-6 or request.quantity < market.min_quantity:
            return Decision(False, "Order check", f"{market.name} trades in steps of {market.quantity_step:g} (minimum {market.min_quantity:g}).")

        # Runaway check (bible section 9): every order a script sends counts.
        now = self.clock()
        if request.source.startswith(("script:", "automation:")) and request.source not in self.paused_sources:
            times = self._source_times.setdefault(request.source, deque())
            times.append(now)
            while times and now - times[0] > 60:
                times.popleft()
            if len(times) > account.rules.max_orders_per_minute_per_script:
                self.paused_sources.add(request.source)
                self.alert("danger", f"{request.source} sent more than {account.rules.max_orders_per_minute_per_script} orders in a minute and was paused.", account.id)

        # Rule 2: risk-reducing orders always go through.
        reducing, excess = self._classify(request, broker)
        if reducing:
            request.reduce_only = True
            return Decision(True, "Rule 2: always let the owner out", "This order reduces risk, so it is always allowed.", reduces_risk=True)

        if not broker.connected:
            return Decision(False, "Rule 3: fail closed", f"The {broker.name} connection is down or not set up ({getattr(broker, 'status', 'not connected')}), so new orders are blocked.")
        state = self.state(account)
        numbers = self.numbers(account)

        # Halts.
        if self.trading_halted:
            return Decision(False, "Kill switch", "Trading is halted by the kill switch. Switch trading back on first.", numbers)
        if state.failed:
            return Decision(False, "Drawdown floor", "This account touched its drawdown floor and has failed. Only closing orders are allowed.", numbers)
        if state.halted:
            return Decision(False, "Account halted", f"This account is halted: {state.halt_reason} Only closing orders are allowed.", numbers)
        if request.source in self.paused_sources:
            return Decision(False, "Runaway orders", f"{request.source} is paused for sending too many orders. Resume it to continue.", numbers)

        problem = self._preflight(account, broker, request)
        if problem:
            return Decision(False, problem[0], problem[1], numbers)

        # Duplicate check (bible section 9).
        now = self.clock()
        for when, acc, sym, side, qty in self._recent:
            if (acc, sym, side, qty) == (account.id, request.symbol, request.side, request.quantity) and now - when <= account.rules.duplicate_window_seconds:
                return Decision(False, "Duplicate order", f"The same order was sent {now - when:.1f} seconds ago. Wait a moment if you really want another.", numbers)

        rules = account.rules
        if rules.allowed_hours and not within_hours(now, rules.allowed_hours, rules.hours_timezone):
            return Decision(False, "Allowed hours", f"This account may only open trades between {rules.allowed_hours} ({rules.hours_timezone}).", numbers)
        if rules.daily_trade_limit is not None and state.trades_today >= rules.daily_trade_limit:
            return Decision(False, "Daily trade limit", f"The daily limit of {rules.daily_trade_limit} trades has been reached.", numbers)

        position = broker.position(account.id, request.symbol)
        new_quantity = position.quantity + request.side.sign * request.quantity
        if rules.max_position_size is not None and abs(new_quantity) > rules.max_position_size + 1e-9:
            return Decision(False, "Max position size", f"This would make the position {abs(new_quantity):g}, above the limit of {rules.max_position_size:g}.", numbers)
        if rules.max_total_quantity is not None:
            total = sum(abs(p.quantity) for p in broker.positions(account.id) if p.symbol != request.symbol) + abs(new_quantity)
            total += sum(r.quantity for r in self._pending.values() if r.account_id == account.id)
            if total > rules.max_total_quantity + 1e-9:
                return Decision(False, "Max contracts", f"This would hold {total:g} in total, above the limit of {rules.max_total_quantity:g}.", numbers)

        # Rule 4 (and 6): worst case.
        problem = self._worst_case_check(account, broker, request, excess, numbers)
        if problem:
            return Decision(False, problem[0], problem[1], numbers)

        self._recent.append((now, account.id, request.symbol, request.side, request.quantity))
        state.trades_today += 1
        self._save_state(account.id)
        return Decision(True, "All rules passed", "Approved.", numbers)

    def _classify(self, request: OrderRequest, broker: BrokerConnector) -> tuple[bool, float]:
        """(reduces risk?, quantity that adds new risk)."""
        position = broker.position(request.account_id, request.symbol)
        if position.is_flat:
            if request.reduce_only:
                return True, 0.0      # nothing to reduce; the broker will simply cancel it
            return False, request.quantity
        opposite = (position.quantity > 0) != (request.side is Side.BUY)
        if opposite and (request.reduce_only or request.quantity <= abs(position.quantity) + 1e-12):
            return True, 0.0
        if request.reduce_only:
            return True, 0.0          # wrong-way reduce-only orders do nothing at the broker
        excess = request.quantity - abs(position.quantity) if opposite else request.quantity
        return False, excess

    def _preflight(self, account: Account, broker: BrokerConnector, request: OrderRequest | None) -> tuple[str, str] | None:
        """Rules 3 and 7: problems that make the numbers untrustworthy."""
        if not broker.supports_broker_stops:
            return ("Rule 7: stops live at the broker", f"{broker.name} can't hold a real stop loss order, so the guard won't send orders there.")
        if not broker.connected:
            return ("Rule 3: fail closed", f"The {broker.name} connection is down, so the guard can't check the account.")
        state = self.state(account)
        if state.balance_mismatch:
            return ("Rule 8: the firm's number wins", "The app's balance and the broker's balance disagree. Check the account, then accept the broker's balance to continue.")
        profile_problem = self.profile_problem(account)
        if profile_problem:
            return ("Rule 3: fail closed", profile_problem)
        if account.is_prop and account.rules.drawdown_amount is None and account.rules.max_daily_loss is None:
            return ("Rule 3: fail closed", "This prop account has no loss limits set, so the guard can't protect it. Fill in its rules first.")
        if request is not None:
            if self.last_price(request.symbol) is None:
                return ("Rule 3: fail closed", f"There is no live price for {request.symbol} yet.")
            status = self.feed_status(request.symbol)
            if status != "ok":
                return ("Rule 3: fail closed", f"The price feed for {request.symbol} is {status}, so new orders are blocked.")
        return None

    def _order_worst_loss(self, market, side: Side, entry: float, stop: float, quantity: float) -> float:
        slippage = market.slippage * quantity * market.point_value
        distance = (entry - stop) * side.sign            # positive when the stop is on the correct side
        return max(0.0, distance) * quantity * market.point_value + 2 * slippage + 2 * market.fee(quantity, entry)

    def _existing_risk(self, account: Account, broker: BrokerConnector, skip_symbol: str | None = None) -> tuple[float, str | None]:
        """Extra loss if every open position and approved working order hits its stop."""
        total = 0.0
        for position in broker.positions(account.id):
            if position.symbol == skip_symbol:
                continue
            market = self.catalog.get(position.symbol)
            stop = broker.stop_price(account.id, position.symbol)
            price = self.last_price(position.symbol)
            if stop is None:
                return 0.0, f"The open {position.symbol} position has no stop loss, so the worst case can't be worked out."
            if price is None:
                return 0.0, f"There is no price for {position.symbol}, so the worst case can't be worked out."
            side = Side.BUY if position.quantity > 0 else Side.SELL
            quantity = abs(position.quantity)
            slippage = market.slippage * quantity * market.point_value
            total += max(0.0, (price - stop) * side.sign) * quantity * market.point_value + slippage + market.fee(quantity, stop)
        working_ids = {o.id for o in broker.working_orders(account.id)}
        for order_id, pending in list(self._pending.items()):
            if order_id not in working_ids:
                del self._pending[order_id]
                continue
            if pending.account_id != account.id:
                continue
            market = self.catalog.get(pending.symbol)
            entry = pending.price or self.last_price(pending.symbol) or 0.0
            if pending.stop_loss is None:
                return 0.0, "A working order has no stop loss, so the worst case can't be worked out."
            total += self._order_worst_loss(market, pending.side, entry, pending.stop_loss, pending.quantity)
        return total, None

    def _worst_case_check(self, account: Account, broker: BrokerConnector, request: OrderRequest, excess: float, numbers: dict) -> tuple[str, str] | None:
        rules = account.rules
        has_limits = rules.max_daily_loss is not None or rules.drawdown_amount is not None
        market = self.catalog.get(request.symbol)
        entry = request.price if request.order_type is not OrderType.MARKET else self.last_price(request.symbol)

        if request.stop_loss is None:
            if rules.require_stop_loss or account.is_prop:
                return ("Rule 4: check the worst case", "Every new order on this account needs a stop loss.")
            if has_limits:
                return ("Rule 4: check the worst case", "Add a stop loss so the guard can check the worst case against your limits.")
            return None
        if (entry - request.stop_loss) * request.side.sign <= 0:
            side = "below" if request.side is Side.BUY else "above"
            return ("Order check", f"A {request.side.value} order's stop loss must be {side} the entry price ({entry:g}).")
        if request.take_profit is not None and (request.take_profit - entry) * request.side.sign <= 0:
            side = "above" if request.side is Side.BUY else "below"
            return ("Order check", f"A {request.side.value} order's target must be {side} the entry price ({entry:g}).")
        if not has_limits:
            return None

        if numbers["used"] >= BLOCK_AT:
            return ("Rule 6: thresholds", f"{numbers['used']:.0%} of the loss room is used, so new risk is blocked.")
        # When adding to a position, its stop moves to the new stop for the whole position.
        position = broker.position(account.id, request.symbol)
        same_way = not position.is_flat and (position.quantity > 0) == (request.side is Side.BUY)
        existing, problem = self._existing_risk(account, broker, skip_symbol=request.symbol if same_way else None)
        if problem:
            return ("Rule 3: fail closed", problem)
        if same_way:
            price = self.last_price(request.symbol)
            quantity = abs(position.quantity)
            existing += max(0.0, (price - request.stop_loss) * request.side.sign) * quantity * market.point_value
            existing += market.slippage * quantity * market.point_value + market.fee(quantity, request.stop_loss)
        order_risk = self._order_worst_loss(market, request.side, entry, request.stop_loss, excess)
        numbers["existing_worst_case"] = round(existing, 2)
        numbers["order_worst_case"] = round(order_risk, 2)

        if "guard_daily_limit" in numbers:
            total_loss = numbers["loss_today"] + existing + order_risk
            numbers["worst_case_loss_today"] = round(total_loss, 2)
            if total_loss > numbers["guard_daily_limit"]:
                return (
                    "Rule 4: check the worst case",
                    f"If the stop is hit, today's loss could reach {total_loss:,.2f}, over the guard's daily limit of "
                    f"{numbers['guard_daily_limit']:,.2f} (firm limit {numbers['daily_limit']:,.2f} minus your {numbers['safety_buffer']:,.2f} buffer).",
                )
        if "guard_floor" in numbers:
            worst_equity = numbers["equity"] - existing - order_risk
            numbers["worst_case_equity"] = round(worst_equity, 2)
            if worst_equity <= numbers["guard_floor"]:
                return (
                    "Rule 4: check the worst case",
                    f"If the stop is hit, equity could fall to {worst_equity:,.2f}, at or below the guard's floor of "
                    f"{numbers['guard_floor']:,.2f} (drawdown floor {numbers['floor']:,.2f} plus your {numbers['safety_buffer']:,.2f} buffer).",
                )
        return None

    def review_cancel(self, account_id: str, order_id: str, source: str = "manual") -> Decision:
        """Rule 2: cancelling always reduces risk. Cancelling a stop loss is the exception: it removes protection."""
        account = self.accounts.get(account_id)
        broker = self.broker_for(account)
        order = next((o for o in broker.working_orders(account_id) if o.id == order_id), None)
        if order is not None and order.role == "stop_loss" and not broker.position(account_id, order.symbol).is_flat:
            decision = Decision(False, "Rule 4: check the worst case", "A stop loss can't be cancelled while its position is open. Close the position, or move the stop.")
        else:
            decision = Decision(True, "Rule 2: always let the owner out", "Cancelling an order is always allowed.", reduces_risk=True)
            decision.stamp = self.issue_stamp("cancel", f"{account_id}|{order_id}")
            self._pending.pop(order_id, None)
        self._log("cancel", account_id, order.symbol if order else None, decision, source)
        return decision

    def review_stop_change(self, account_id: str, symbol: str, new_stop: float, source: str = "manual") -> Decision:
        """Moving a stop closer to the price is always allowed. Moving it further away adds risk and is checked."""
        try:
            account = self.accounts.get(account_id)
            broker = self.broker_for(account)
            position = broker.position(account_id, symbol)
            price = self.last_price(symbol)
            if position.is_flat:
                decision = Decision(False, "Order check", "There is no open position to protect.")
            elif price is None:
                decision = Decision(False, "Rule 3: fail closed", f"There is no live price for {symbol}.")
            else:
                side = Side.BUY if position.quantity > 0 else Side.SELL
                if (price - new_stop) * side.sign <= 0:
                    decision = Decision(False, "Order check", "That stop is on the wrong side of the price; it would fill straight away. Close the position instead.")
                else:
                    old_stop = broker.stop_price(account_id, symbol)
                    tighter = old_stop is not None and (new_stop - old_stop) * side.sign >= 0
                    if tighter:
                        decision = Decision(True, "Rule 2: always let the owner out", "Moving the stop closer to the price reduces risk.", reduces_risk=True)
                    else:
                        decision = self._review_wider_stop(account, broker, symbol, side, abs(position.quantity), new_stop, old_stop, price)
        except Exception as problem:
            log.exception("Risk guard could not check a stop change")
            decision = Decision(False, "Rule 3: fail closed", f"The guard could not check this change safely ({problem}).")
        if decision.approved:
            decision.stamp = self.issue_stamp("modify_stop", f"{account_id}|{symbol}|{new_stop}")
        self._log("modify_stop", account_id, symbol, decision, source)
        return decision

    def _review_wider_stop(self, account, broker, symbol, side, quantity, new_stop, old_stop, price) -> Decision:
        numbers = self.numbers(account)
        if self.trading_halted or numbers["blocked"]:
            return Decision(False, "Rule 2: moving a stop away adds risk", "Moving a stop further away adds risk, and new risk is blocked right now.", numbers)
        problem = self._preflight(account, broker, None)
        if problem:
            return Decision(False, problem[0], problem[1], numbers)
        rules = account.rules
        if rules.max_daily_loss is None and rules.drawdown_amount is None:
            return Decision(True, "No loss limits", "This account has no loss limits, so the wider stop is allowed.", numbers)
        # Everything else's worst case, plus this position's worst case at the new stop.
        others, problem = self._existing_risk(account, broker, skip_symbol=symbol)
        if problem:
            return Decision(False, "Rule 3: fail closed", problem, numbers)
        market = self.catalog.get(symbol)
        slippage = market.slippage * quantity * market.point_value
        new_risk = max(0.0, (price - new_stop) * side.sign) * quantity * market.point_value + slippage + market.fee(quantity, new_stop)
        total = others + new_risk
        if "guard_daily_limit" in numbers and numbers["loss_today"] + total > numbers["guard_daily_limit"]:
            return Decision(False, "Rule 4: check the worst case", "With the stop moved there, a stop-out could break the guard's daily limit.", numbers)
        if "guard_floor" in numbers and numbers["equity"] - total <= numbers["guard_floor"]:
            return Decision(False, "Rule 4: check the worst case", "With the stop moved there, a stop-out could reach the guard's drawdown floor.", numbers)
        return Decision(True, "Rule 4: check the worst case", "The wider stop still fits inside every limit.", numbers)

    def review_target_change(self, account_id: str, symbol: str, new_target: float | None, source: str = "manual") -> Decision:
        """Targets only ever close positions, so changing one never adds risk."""
        decision = Decision(True, "Rule 2: always let the owner out", "Targets only close positions, so changing one is allowed.", reduces_risk=True)
        decision.stamp = self.issue_stamp("modify_target", f"{account_id}|{symbol}|{new_target}")
        self._log("modify_target", account_id, symbol, decision, source)
        return decision

    def review_price_change(self, account_id: str, order_id: str, new_price: float, source: str = "manual") -> Decision:
        """Moving a working entry order is checked like a new order at the new price."""
        account = self.accounts.get(account_id)
        broker = self.broker_for(account)
        order = next((o for o in broker.working_orders(account_id) if o.id == order_id), None)
        if order is None:
            decision = Decision(False, "Order check", "That order is no longer working.")
        elif order.role != "entry":
            decision = Decision(True, "Rule 2: always let the owner out", "Closing orders can always be moved.", reduces_risk=True)
        else:
            pending = self._pending.get(order_id)
            if self.trading_halted:
                decision = Decision(False, "Kill switch", "Trading is halted by the kill switch.")
            elif pending is not None and pending.stop_loss is not None and (new_price - pending.stop_loss) * order.side.sign <= 0:
                decision = Decision(False, "Order check", "That would put the entry beyond its own stop loss.")
            else:
                decision = Decision(True, "Order moved", "Moving a working order is allowed.")
                if pending is not None:
                    pending.price = new_price
        if decision.approved:
            decision.stamp = self.issue_stamp("modify_price", f"{account_id}|{order_id}|{new_price}")
        self._log("modify_price", account_id, order.symbol if order else None, decision, source)
        return decision

    def remember_pending(self, order_id: str, request: OrderRequest) -> None:
        if not request.reduce_only and request.order_type is not OrderType.MARKET:
            self._pending[order_id] = request

    # ======================================================================
    # Monitoring: prices, fills, thresholds, balances
    # ======================================================================

    def on_price(self, symbol: str) -> None:
        """Recalculate every account holding this symbol (bible: after every price tick)."""
        for account in self.accounts.all():
            broker = self.broker_for(account)
            if not broker.connected:
                continue
            try:
                if any(p.symbol == symbol for p in broker.positions(account.id)):
                    self.evaluate(account)
            except Exception:
                log.exception("Could not evaluate account %s", account.name)

    def on_fill(self, fill: dict) -> None:
        account = self.accounts.get(fill["account_id"])
        state = self.state(account)
        if state.expected_balance is not None:
            state.expected_balance += fill["realized"] - fill["fee"]
        if state.trading_day and state.trading_day not in state.days_traded:
            state.days_traded.append(state.trading_day)
        self._pending.pop(fill["order_id"], None)
        self._save_state(account.id)
        self.evaluate(account)
        self.reconcile_balance(account)

    def evaluate(self, account: Account) -> dict:
        """Update the drawdown tracker and act on the 70% and 100% thresholds."""
        state = self.state(account)
        tracker = self.tracker(account)
        broker = self.broker_for(account)
        equity = broker.snapshot(account.id).equity
        if tracker:
            was_failed = tracker.state.failed
            tracker.on_equity(equity)
            state.drawdown = tracker.state.to_dict()
            if tracker.state.failed and not was_failed:
                state.failed = True
                self.alert("danger", f"{account.name}: equity {equity:,.2f} touched the drawdown floor {tracker.state.floor:,.2f}. The account has failed.", account.id)
                self.flatten_account(account.id, "drawdown floor touched")
        numbers = self.numbers(account)
        if numbers["used"] >= WARN_AT and not state.warned:
            state.warned = True
            self.alert("warning", f"{account.name}: {numbers['used']:.0%} of the loss room is used.", account.id)
        if numbers["used"] >= BLOCK_AT and not state.limit_hit:
            state.limit_hit = True
            self.alert("danger", f"{account.name}: the guard's loss limit is reached. New risk is blocked.", account.id)
            if account.rules.auto_flatten_at_limit:
                state.halted = True
                state.halt_reason = "the guard's loss limit was reached and everything was closed."
                self.flatten_account(account.id, "loss limit reached")
        self._save_state(account.id)
        self.bus.publish("account", {"account_id": account.id, "numbers": numbers})
        return numbers

    def reconcile_balance(self, account: Account) -> None:
        """Rule 8: compare our running balance with the broker's."""
        broker = self.broker_for(account)
        if not broker.connected:
            return
        state = self.state(account)
        reported = broker.snapshot(account.id).balance
        if not broker.reports_fills:
            # This connector doesn't stream fills yet, so our own running balance can't be
            # kept; follow the broker's number (see NEEDS_NATHAN.md: needed before going live).
            state.expected_balance = reported
            self._save_state(account.id)
            return
        if state.expected_balance is None:
            state.expected_balance = reported
        gap = abs(reported - state.expected_balance)
        if gap > account.rules.balance_tolerance and not state.balance_mismatch:
            state.balance_mismatch = True
            self.alert("danger", f"{account.name}: the broker reports {reported:,.2f} but the app expected {state.expected_balance:,.2f}. New risk is blocked until you check it.", account.id)
        self._save_state(account.id)

    def reconcile_balances(self) -> None:
        for account in self.accounts.all():
            try:
                self.reconcile_balance(account)
            except Exception:
                log.exception("Balance check failed for %s", account.name)

    def accept_broker_balance(self, account_id: str) -> None:
        account = self.accounts.get(account_id)
        state = self.state(account)
        state.expected_balance = self.broker_for(account).snapshot(account_id).balance
        state.balance_mismatch = False
        self._save_state(account_id)
        self._log_simple("accept_balance", account_id, "Owner accepted the broker's balance.")

    def resume_account(self, account_id: str) -> None:
        """The owner switches a halted account back on. A failed account stays failed."""
        account = self.accounts.get(account_id)
        state = self.state(account)
        state.halted = False
        state.halt_reason = ""
        self._save_state(account_id)
        self._log_simple("resume_account", account_id, "Owner resumed the account.")

    def reset_account_state(self, account_id: str) -> None:
        """Start an account's tracking from scratch (used when a paper account is reset)."""
        self._states.pop(account_id, None)
        self._trackers.pop(account_id, None)
        self.journal.save_state("account_state", account_id, asdict(AccountState()))

    def resume_source(self, source: str) -> None:
        self.paused_sources.discard(source)
        self._source_times.pop(source, None)
        self._log_simple("resume_source", None, f"Owner resumed {source}.")

    def set_trading_halted(self, halted: bool, reason: str) -> None:
        self.trading_halted = halted
        self.journal.save_state("account_state", "__kill_switch__", {"halted": halted, "reason": reason, "time": self.clock()})
        self._log_simple("kill_switch" if halted else "resume_trading", None, reason)
        self.bus.publish("trading", {"halted": halted, "reason": reason})

    # ======================================================================
    # Logging and alerts
    # ======================================================================

    def alert(self, level: str, message: str, account_id: str | None = None) -> None:
        log.warning("ALERT [%s] %s", level, message)
        entry = self.journal.record_alert(self.clock(), level, message, account_id)
        self.bus.publish("alert", entry)

    def _log(self, action: str, account_id: str | None, symbol: str | None, decision: Decision, source: str) -> None:
        entry = {
            "time": self.clock(), "account_id": account_id, "symbol": symbol, "action": action,
            "approved": decision.approved, "rule": decision.rule, "reason": decision.reason,
            "numbers": decision.numbers, "source": source,
        }
        self.journal.record_decision(entry)
        log.info("Guard %s %s %s: %s (%s)", "APPROVED" if decision.approved else "BLOCKED", action, symbol or "", decision.reason, decision.rule)
        self.bus.publish("guard", entry)

    def _log_simple(self, action: str, account_id: str | None, reason: str) -> None:
        self._log(action, account_id, None, Decision(True, "Owner action", reason), "owner")
