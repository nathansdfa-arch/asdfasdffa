"""Prop firm rule profiles (bible section 9) and the evaluation simulator (section 8).

Profiles live in config/prop_firms.json. A profile is only usable once the
owner has filled in every number from the firm's current rule page and set
confirmed_by_owner to true. Until then the risk guard blocks new orders on
any account using it (rule 3, fail closed). The app never guesses a figure.
"""

import json
from pathlib import Path

from engine.core.markets import CONFIG_DIR
from engine.execution.accounts import Account, RiskRules

REQUIRED = ["starting_balance", "drawdown_amount", "drawdown_method", "reset_time", "reset_timezone"]


class ProfileStore:
    def __init__(self, path: Path | None = None):
        self.path = path or CONFIG_DIR / "prop_firms.json"

    def all(self) -> list[dict]:
        return json.loads(self.path.read_text(encoding="utf-8"))["profiles"]

    def get(self, profile_id: str) -> dict:
        for profile in self.all():
            if profile["id"] == profile_id:
                return profile
        raise KeyError(f"There is no prop firm profile '{profile_id}'.")

    def missing(self, profile: dict) -> list[str]:
        return [key for key in REQUIRED if profile.get(key) in (None, "")]

    def problem(self, account: Account) -> str | None:
        """Why this account's profile can't be trusted yet, or None if it can."""
        if not account.profile_id:
            return None
        try:
            profile = self.get(account.profile_id)
        except KeyError as error:
            return str(error)
        missing = self.missing(profile)
        if missing:
            return f"The {profile['firm']} profile is missing: {', '.join(missing)}. Fill them in from the firm's rule page (config/prop_firms.json)."
        if not profile.get("confirmed_by_owner"):
            return f"The {profile['firm']} numbers haven't been confirmed against the firm's rule page yet."
        return None

    def rules_for(self, profile: dict, safety_buffer: float, current: RiskRules | None = None) -> RiskRules:
        """Account rules made from a profile. The owner's own settings (buffer, hours) are kept."""
        rules = current or RiskRules()
        rules.drawdown_amount = profile.get("drawdown_amount")
        rules.drawdown_method = profile.get("drawdown_method") or "intraday"
        rules.drawdown_lock = profile.get("lock_level")
        rules.max_daily_loss = profile.get("daily_loss_limit")
        rules.max_total_quantity = profile.get("max_contracts")
        rules.allowed_hours = profile.get("allowed_hours") or rules.allowed_hours
        rules.reset_time = profile.get("reset_time") or rules.reset_time
        rules.reset_timezone = profile.get("reset_timezone") or rules.reset_timezone
        rules.require_stop_loss = bool(profile.get("stop_loss_required", True))
        rules.profit_target = profile.get("profit_target")
        rules.safety_buffer = safety_buffer
        rules.auto_flatten_at_limit = True     # bible rule 6: on by default for prop accounts
        return rules


def evaluation_status(account: Account, numbers: dict, profile: dict | None) -> dict | None:
    """Progress of a simulated prop firm evaluation."""
    if not account.rules.profit_target:
        return None
    target = account.rules.profit_target
    profit = numbers.get("equity", account.starting_balance) - account.starting_balance
    min_days = (profile or {}).get("min_trading_days") or 0
    days = numbers.get("days_traded", 0)
    if numbers.get("failed"):
        status, message = "failed", "The drawdown floor was touched. A real evaluation would end here."
    elif profit >= target and days >= min_days:
        status, message = "passed", "Profit target reached with enough trading days. A real evaluation would pass here (check the firm's other rules too)."
    elif profit >= target:
        status, message = "target reached", f"Profit target reached; {min_days - days} more trading day(s) needed."
    else:
        status, message = "in progress", f"{max(0.0, target - profit):,.2f} to go."
    return {
        "status": status, "message": message, "profit": round(profit, 2), "target": target,
        "progress": round(max(0.0, min(1.0, profit / target)) * 100, 1) if target else 0,
        "days_traded": days, "min_trading_days": min_days,
    }
