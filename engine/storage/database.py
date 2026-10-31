"""The local database.

SQLite keeps the whole database in a single file on the owner's computer. No
database server needs installing, and nothing is sent anywhere.

The database layout (its "schema") changes as the app grows. Each change is a
numbered step in MIGRATIONS below. On startup the app checks which steps the
database has already had and applies only the new ones, in order. Steps are
never edited once released; a change is always a new step at the end.
"""

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# Each entry is (step number, short description, SQL to run).
MIGRATIONS = [
    (
        1,
        "Create the settings table",
        """
        CREATE TABLE settings (
            key        TEXT PRIMARY KEY,  -- the setting's name, e.g. 'display_timezone'
            value      TEXT NOT NULL,     -- the value, stored as JSON text
            updated_at TEXT NOT NULL      -- when it last changed, in UTC
        );
        """,
    ),
]


def utc_now() -> str:
    """The current time in UTC as text, e.g. '2026-10-31T01:02:03+00:00'."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: Path) -> sqlite3.Connection:
    """Open the database file. Each caller opens its own short-lived connection."""
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row  # lets code read columns by name: row["key"]
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize(db_path: Path) -> int:
    """Create the database if needed and bring it up to date. Returns the schema version."""
    with connect(db_path) as conn:
        # WAL mode lets the app read while it writes, and survives crashes well.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version    INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        current = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] or 0

        for version, description, sql in MIGRATIONS:
            if version <= current:
                continue
            log.info("Database update %d: %s", version, description)
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (version, utc_now()),
            )
            current = version

    log.info("Database ready at %s (schema version %d)", db_path, current)
    return current
