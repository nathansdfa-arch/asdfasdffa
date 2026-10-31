"""Daily local backups (bible section 11): scripts, settings, trade history and
account state are all in the one database file, so a backup is a safe copy
of that file. The last 30 are kept in the "backups" folder of the data folder.
"""

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

KEEP = 30


class Backups:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.folder = db_path.parent / "backups"

    def list(self) -> list[dict]:
        if not self.folder.exists():
            return []
        files = sorted(self.folder.glob("trading_app-*.db"), reverse=True)
        return [{"name": f.name, "size": f.stat().st_size} for f in files]

    def latest_date(self) -> str | None:
        files = self.list()
        return files[0]["name"][len("trading_app-"):len("trading_app-") + 10] if files else None

    def make(self) -> str:
        """Copy the database safely while the app keeps running (SQLite's own backup feature)."""
        self.folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
        target = self.folder / f"trading_app-{stamp}.db"
        source = sqlite3.connect(self.db_path)
        copy = sqlite3.connect(target)
        with copy:
            source.backup(copy)
        copy.close()
        source.close()
        for old in sorted(self.folder.glob("trading_app-*.db"), reverse=True)[KEEP:]:
            old.unlink()
        log.info("Backup saved: %s", target.name)
        return target.name

    def make_if_due(self) -> str | None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.latest_date() != today:
            return self.make()
        return None
