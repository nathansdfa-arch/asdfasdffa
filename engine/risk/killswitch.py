"""The kill switch (bible section 9).

One press, no confirmation, from any screen. Four steps, in order:
  1. stop every automation and running strategy
  2. cancel every working order
  3. close every position at market
  4. check with the broker that positions are zero; retry, and alert if not

Trading then stays halted until the owner switches it back on.
"""

import asyncio
import logging
from typing import Callable

from engine.execution.accounts import AccountStore
from engine.execution.orders import OrderService
from engine.risk.guard import RiskGuard

log = logging.getLogger(__name__)

RETRIES = 3
WAIT_BETWEEN_CHECKS = 0.5


class KillSwitch:
    def __init__(self, accounts: AccountStore, guard: RiskGuard, orders: OrderService, broker_for):
        self.accounts = accounts
        self.guard = guard
        self.orders = orders
        self.broker_for = broker_for
        # Each part that runs automatically registers a "stop everything" function here.
        self.stoppers: list[Callable[[], None]] = []

    async def trigger(self, reason: str = "Kill switch pressed") -> dict:
        report = {"steps": [], "ok": True}
        # Halt first, so nothing new can start while we clean up.
        self.guard.set_trading_halted(True, reason)

        # Step 1: stop automations and strategies.
        stopped = 0
        for stop in self.stoppers:
            try:
                stop()
                stopped += 1
            except Exception:
                log.exception("A stopper failed during the kill switch")
                report["ok"] = False
        report["steps"].append(f"Stopped {stopped} automatic runner(s).")

        accounts = [a for a in self.accounts.all() if self.broker_for(a).connected]

        # Step 2: cancel every working order (entry orders; protective stops go with their positions).
        cancelled = 0
        for account in accounts:
            cancelled += sum(1 for r in self.orders.cancel_all(account.id, source="kill switch") if r["ok"])
        report["steps"].append(f"Cancelled {cancelled} working order(s).")

        # Steps 3 and 4: close positions, then check and retry.
        for attempt in range(1, RETRIES + 1):
            open_positions = []
            for account in accounts:
                broker = self.broker_for(account)
                for position in broker.positions(account.id):
                    self.orders.close_position(account.id, position.symbol, source="kill switch")
            await asyncio.sleep(WAIT_BETWEEN_CHECKS if attempt > 1 else 0)
            for account in accounts:
                broker = self.broker_for(account)
                open_positions += [f"{account.name} {p.symbol}" for p in broker.positions(account.id)]
                # Anything left working (including protective orders of now-closed positions).
                for order in broker.working_orders(account.id):
                    if broker.position(account.id, order.symbol).is_flat:
                        self.orders.cancel(account.id, order.id, source="kill switch")
            if not open_positions:
                report["steps"].append(f"Closed all positions (check {attempt}: zero positions).")
                break
            report["steps"].append(f"Check {attempt}: still open: {', '.join(open_positions)}. Retrying.")
        else:
            report["ok"] = False
            self.guard.alert("danger", "Kill switch: some positions could not be confirmed closed. Check your broker platform now!")

        working = sum(len(self.broker_for(a).working_orders(a.id)) for a in accounts)
        report["working_orders_left"] = working
        report["positions_left"] = sum(len(self.broker_for(a).positions(a.id)) for a in accounts)
        self.guard.alert("danger" if not report["ok"] else "warning", "Kill switch used: " + " ".join(report["steps"]))
        log.warning("Kill switch report: %s", report)
        return report

    def resume(self) -> None:
        self.guard.set_trading_halted(False, "Owner switched trading back on")
