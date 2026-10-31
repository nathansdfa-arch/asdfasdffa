"""Rithmic connector for futures (Tradeify, Lucid). Phase 8 PLACEHOLDER.

Why this is a placeholder: Rithmic's API (R | Protocol) and its message
definitions are provided by Rithmic after you sign up with them, and a
self-built app usually has to pass Rithmic's conformance test before it may
connect to real or prop accounts (bible section 10). Neither has happened
yet, so this connector reports "not configured" and the risk guard blocks
every order on Rithmic accounts (rule 3, fail closed).

What is ready: the account type, where credentials will be stored (Windows
Credential Manager), and the interface the real connector must fill in.
See NEEDS_NATHAN.md for the steps to unblock it.
"""

from engine.core.models import AccountSnapshot, Order, OrderRequest, Position
from engine.execution.broker import BrokerConnector, NotConfigured, OrderRefused


class RithmicConnector(BrokerConnector):
    name = "Rithmic"
    supports_broker_stops = True     # Rithmic supports server-side brackets

    def __init__(self, account_id: str, settings: dict, check_stamp=None):
        super().__init__(check_stamp)
        self.account_id = account_id
        self.settings = settings
        self.status = "Not set up: waiting for Rithmic API access and conformance approval."

    @property
    def connected(self) -> bool:
        return False

    def snapshot(self, account_id: str) -> AccountSnapshot:
        raise NotConfigured(self.status)

    def positions(self, account_id: str) -> list[Position]:
        return []

    def working_orders(self, account_id: str) -> list[Order]:
        return []

    def _place(self, request: OrderRequest) -> Order:
        raise OrderRefused(self.status)

    def _cancel(self, account_id: str, order_id: str) -> None:
        raise OrderRefused(self.status)

    def _modify_stop(self, account_id: str, symbol: str, new_stop: float) -> None:
        raise OrderRefused(self.status)
