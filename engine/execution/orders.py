"""The order service: the single path every order takes.

    script / button / automation
        -> OrderService.submit()
        -> RiskGuard.review_order()   approve or block, logged either way
        -> broker.place_order()       refuses anything without the guard's stamp

Nothing else in the app talks to brokers to place, change or cancel orders.
"""

import logging

from engine.core.models import OrderRequest, OrderType, Side
from engine.execution.accounts import Account, AccountStore
from engine.execution.broker import BrokerConnector, OrderRefused
from engine.risk.guard import Decision, RiskGuard

log = logging.getLogger(__name__)


class OrderResult(dict):
    """{"ok": bool, "message": str, "decision": {...}, "order": {...} or None}"""


class OrderService:
    def __init__(self, accounts: AccountStore, guard: RiskGuard, broker_for):
        self.accounts = accounts
        self.guard = guard
        self.broker_for = broker_for
        guard.flatten_account = self.flatten_account

    def _broker(self, account_id: str) -> tuple[Account, BrokerConnector]:
        account = self.accounts.get(account_id)
        return account, self.broker_for(account)

    def submit(self, request: OrderRequest) -> OrderResult:
        decision = self.guard.review_order(request)
        if not decision.approved:
            return OrderResult(ok=False, message=decision.reason, decision=decision.to_dict(), order=None)
        account, broker = self._broker(request.account_id)
        try:
            order = broker.place_order(request, decision.stamp)
        except OrderRefused as problem:
            return OrderResult(ok=False, message=str(problem), decision=decision.to_dict(), order=None)
        self.guard.remember_pending(order.id, request)
        return OrderResult(ok=True, message=decision.reason, decision=decision.to_dict(), order=order.to_dict())

    def cancel(self, account_id: str, order_id: str, source: str = "manual") -> OrderResult:
        decision = self.guard.review_cancel(account_id, order_id, source)
        return self._apply(decision, lambda broker, stamp: broker.cancel_order(account_id, order_id, stamp), account_id)

    def move_stop(self, account_id: str, symbol: str, new_stop: float, source: str = "manual") -> OrderResult:
        decision = self.guard.review_stop_change(account_id, symbol, new_stop, source)
        return self._apply(decision, lambda broker, stamp: broker.modify_stop(account_id, symbol, new_stop, stamp), account_id)

    def move_target(self, account_id: str, symbol: str, new_target: float | None, source: str = "manual") -> OrderResult:
        decision = self.guard.review_target_change(account_id, symbol, new_target, source)
        return self._apply(decision, lambda broker, stamp: broker.modify_target(account_id, symbol, new_target, stamp), account_id)

    def move_order(self, account_id: str, order_id: str, new_price: float, source: str = "manual") -> OrderResult:
        decision = self.guard.review_price_change(account_id, order_id, new_price, source)
        return self._apply(decision, lambda broker, stamp: broker.modify_order_price(account_id, order_id, new_price, stamp), account_id)

    def _apply(self, decision: Decision, action, account_id: str) -> OrderResult:
        if not decision.approved:
            return OrderResult(ok=False, message=decision.reason, decision=decision.to_dict(), order=None)
        _, broker = self._broker(account_id)
        try:
            action(broker, decision.stamp)
        except OrderRefused as problem:
            return OrderResult(ok=False, message=str(problem), decision=decision.to_dict(), order=None)
        return OrderResult(ok=True, message=decision.reason, decision=decision.to_dict(), order=None)

    def close_position(self, account_id: str, symbol: str, source: str = "manual") -> OrderResult:
        _, broker = self._broker(account_id)
        position = broker.position(account_id, symbol)
        if position.is_flat:
            return OrderResult(ok=True, message="Already flat.", decision=None, order=None)
        request = OrderRequest(
            account_id=account_id, symbol=symbol,
            side=Side.SELL if position.quantity > 0 else Side.BUY,
            quantity=abs(position.quantity), order_type=OrderType.MARKET,
            source=source, reduce_only=True,
        )
        return self.submit(request)

    def cancel_all(self, account_id: str, source: str = "manual") -> list[OrderResult]:
        _, broker = self._broker(account_id)
        results = []
        # Entry orders first, then protective orders once their positions are gone.
        for order in sorted(broker.working_orders(account_id), key=lambda o: o.role in ("stop_loss", "take_profit")):
            if order.role in ("stop_loss", "take_profit") and not broker.position(account_id, order.symbol).is_flat:
                continue
            results.append(self.cancel(account_id, order.id, source))
        return results

    def flatten_account(self, account_id: str, reason: str = "") -> dict:
        """Cancel entry orders, then close every position at market."""
        _, broker = self._broker(account_id)
        cancelled = self.cancel_all(account_id, source=f"flatten: {reason}")
        closed = [self.close_position(account_id, p.symbol, source=f"flatten: {reason}") for p in broker.positions(account_id)]
        log.warning("Flattened account %s (%s)", account_id, reason)
        return {"cancelled": len(cancelled), "closed": len(closed)}
