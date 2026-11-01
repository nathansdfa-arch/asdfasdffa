"""Jarvis access: the owner's voice assistant gets its own key and its own limits.

Jarvis (nathan's voice assistant, repo jarvis-relay) talks to the engine through
the /api/jarvis addresses only, with the key the owner creates in Settings.
On top of the risk guard, which checks every Jarvis order like any other:

  - Jarvis is off until the owner creates a key, and the owner can switch it off.
  - Jarvis may only open new trades on PAPER accounts, and only on the accounts
    the owner allowed (none listed = every paper account).
  - Each order has a contract cap and there is a daily order cap.
  - Closing, tightening and the kill switch are always allowed.

The key is stored as a hash, so it can't be read back from the database.

The owner PIN also lives here. Once set, the buttons only the owner should
press (switching to live, resuming after the kill switch, changing rules,
Jarvis's own settings...) need it, so no program on this computer can press
them by calling the engine directly.
"""

import hashlib
import hmac
import json
import logging
import secrets
import time
from datetime import datetime
from pathlib import Path

from engine.security.auth import check_password, hash_password
from engine.storage.database import connect

log = logging.getLogger(__name__)

JARVIS_SOURCE = "automation:jarvis"
DEFAULTS = {"enabled": False, "max_quantity": 1.0, "max_orders_per_day": 20, "allowed_account_ids": []}
PIN_MAX_FAILURES = 5
PIN_LOCK_SECONDS = 60


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class JarvisAccess:
    def __init__(self, db_path: Path, clock=time.time):
        self.db_path = db_path
        self.clock = clock
        self._pin_failures = 0
        self._pin_locked_until = 0.0

    # ---- storage (the auth table holds small key/value security settings) ----------

    def _get(self, key: str) -> str | None:
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT value FROM auth WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def _set(self, key: str, value: str) -> None:
        with connect(self.db_path) as conn:
            conn.execute("INSERT OR REPLACE INTO auth (key, value) VALUES (?, ?)", (key, value))

    def _config(self) -> dict:
        stored = json.loads(self._get("jarvis_config") or "{}")
        return {**DEFAULTS, **stored}

    def _today(self) -> str:
        return datetime.fromtimestamp(self.clock()).date().isoformat()

    def _counter(self) -> dict:
        counter = json.loads(self._get("jarvis_orders_today") or "{}")
        if counter.get("day") != self._today():
            counter = {"day": self._today(), "count": 0}
        return counter

    # ---- the owner's side ---------------------------------------------------------

    def status(self) -> dict:
        config = self._config()
        return config | {"key_set": self._get("jarvis_key_hash") is not None, "orders_today": self._counter()["count"]}

    def new_key(self) -> str:
        """Make a new key, switch Jarvis on, and return the key. It is shown once only."""
        key = "jv_" + secrets.token_urlsafe(32)
        self._set("jarvis_key_hash", _hash_key(key))
        self.configure({"enabled": True})
        log.warning("A new Jarvis key was created; any older key stops working")
        return key

    def configure(self, changes: dict) -> dict:
        config = self._config()
        if "enabled" in changes:
            config["enabled"] = bool(changes["enabled"])
        if "max_quantity" in changes:
            value = float(changes["max_quantity"])
            if not 0 < value <= 100:
                raise ValueError("Jarvis's most contracts per order must be more than 0 and at most 100.")
            config["max_quantity"] = value
        if "max_orders_per_day" in changes:
            value = changes["max_orders_per_day"]
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 500:
                raise ValueError("Jarvis's orders per day must be a whole number from 0 to 500.")
            config["max_orders_per_day"] = value
        if "allowed_account_ids" in changes:
            ids = changes["allowed_account_ids"]
            if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
                raise ValueError("Allowed accounts must be a list of account ids.")
            config["allowed_account_ids"] = ids
        self._set("jarvis_config", json.dumps(config))
        return self.status()

    # ---- Jarvis's side ------------------------------------------------------------

    def key_ok(self, key: str | None) -> bool:
        stored = self._get("jarvis_key_hash")
        if not key or not stored:
            return False
        return hmac.compare_digest(stored, _hash_key(key))

    def problem_for(self, key: str | None) -> str | None:
        """Why this request may not use the Jarvis door, or None if it may."""
        if not self.key_ok(key):
            return "Jarvis key missing or wrong. Create one in Settings, Jarvis."
        if not self._config()["enabled"]:
            return "Jarvis trading is switched off in Settings."
        return None

    def account_problem(self, account) -> str | None:
        """Jarvis may only add risk on allowed PAPER accounts."""
        if account.mode != "PAPER":
            return f"{account.name} is a LIVE account. Jarvis can only trade paper accounts."
        allowed = self._config()["allowed_account_ids"]
        if allowed and account.id not in allowed:
            return f"Jarvis isn't allowed to trade {account.name}. The owner can allow it in Settings."
        return None

    def order_problem(self, quantity: float) -> str | None:
        config = self._config()
        if quantity > config["max_quantity"]:
            return f"Jarvis may send at most {config['max_quantity']:g} per order."
        if self._counter()["count"] >= config["max_orders_per_day"]:
            return f"Jarvis already sent its {config['max_orders_per_day']} orders for today."
        return None

    def count_order(self) -> None:
        counter = self._counter()
        counter["count"] += 1
        self._set("jarvis_orders_today", json.dumps(counter))

    # ---- the owner PIN ------------------------------------------------------------

    def pin_set(self) -> bool:
        return self._get("owner_pin_hash") is not None

    def pin_ok(self, pin: str | None) -> bool:
        """Check the PIN. Locks for a minute after five wrong tries."""
        if not self.pin_set():
            return True
        if self.clock() < self._pin_locked_until:
            return False
        if pin and check_password(pin, self._get("owner_pin_hash")):
            self._pin_failures = 0
            return True
        self._pin_failures += 1
        if self._pin_failures >= PIN_MAX_FAILURES:
            self._pin_locked_until = self.clock() + PIN_LOCK_SECONDS
            self._pin_failures = 0
            log.warning("Owner PIN locked for %s seconds after repeated wrong tries", PIN_LOCK_SECONDS)
        return False

    def set_pin(self, pin: str) -> None:
        if not isinstance(pin, str) or not pin.isdigit() or not 4 <= len(pin) <= 12:
            raise ValueError("The PIN must be 4 to 12 digits.")
        self._set("owner_pin_hash", hash_password(pin))
        log.warning("Owner PIN changed")
