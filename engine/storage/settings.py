"""Settings: the owner's choices, saved in the database so they survive a restart.

Only settings listed in SETTINGS below can be saved. Each one has a default
value and a check that rejects bad values with a plain English message. This
stops typos or broken screens from saving nonsense.

Later phases add their settings here (theme, accent color, safety buffer, ...).
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from engine.storage.database import connect, utc_now

log = logging.getLogger(__name__)


class SettingError(ValueError):
    """Raised when a setting name or value is not allowed. The message is shown to the owner."""


@dataclass(frozen=True)
class SettingSpec:
    label: str                          # shown on screen
    default: Any                        # used until the owner changes it
    check: Callable[[Any], str | None]  # returns an error message, or None if the value is fine


def _check_timezone(value: Any) -> str | None:
    if not isinstance(value, str):
        return "The time zone must be text, for example 'America/New_York'."
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        return f"'{value}' is not a known time zone. Try a name like 'America/New_York' or 'Europe/London'."
    return None


def _check_glow(value: Any) -> str | None:
    # bool is a kind of int in Python, so rule it out explicitly.
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        return "Glow strength must be a whole number from 0 (off) to 100."
    return None


def _check_bool(value: Any) -> str | None:
    if not isinstance(value, bool):
        return "This setting must be on (true) or off (false)."
    return None


SETTINGS: dict[str, SettingSpec] = {
    # Times are stored in UTC and shown in this time zone (bible section 4).
    "display_timezone": SettingSpec("Display time zone", "UTC", _check_timezone),
    # Strength of the soft glowing borders; 0 turns them off (bible section 6A).
    "glow_strength": SettingSpec("Glow strength", 50, _check_glow),
    # Turns off non-essential animation (bible section 6A).
    "reduce_motion": SettingSpec("Reduce motion", False, _check_bool),
}


class SettingsStore:
    """Reads and writes settings in the database."""

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def get_all(self) -> dict[str, Any]:
        """Every setting, using the saved value where there is one and the default otherwise."""
        values = {key: spec.default for key, spec in SETTINGS.items()}
        with connect(self.db_path) as conn:
            for row in conn.execute("SELECT key, value FROM settings"):
                if row["key"] in SETTINGS:  # ignore settings that were removed from the app
                    values[row["key"]] = json.loads(row["value"])
        return values

    def get(self, key: str) -> Any:
        self._require_known(key)
        return self.get_all()[key]

    def set(self, key: str, value: Any) -> None:
        """Check and save one setting. Raises SettingError with a plain English reason if not allowed."""
        spec = self._require_known(key)
        problem = spec.check(value)
        if problem:
            raise SettingError(problem)
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, json.dumps(value), utc_now()),
            )
        log.info("Setting changed: %s = %r", key, value)

    @staticmethod
    def _require_known(key: str) -> SettingSpec:
        if key not in SETTINGS:
            raise SettingError(f"There is no setting called '{key}'.")
        return SETTINGS[key]
