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
    (
        2,
        "Create the candle cache",
        """
        CREATE TABLE candles (
            symbol    TEXT NOT NULL,     -- 'BYBIT:BTCUSDT'
            timeframe TEXT NOT NULL,     -- '1m', '1h', ...
            time      INTEGER NOT NULL,  -- candle open time, unix seconds UTC
            open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
            volume REAL NOT NULL,
            PRIMARY KEY (symbol, timeframe, time)
        ) WITHOUT ROWID;

        -- Which stretch of time has already been fetched, so it is not fetched again.
        CREATE TABLE candle_coverage (
            symbol    TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            start     INTEGER NOT NULL,
            end       INTEGER NOT NULL,
            PRIMARY KEY (symbol, timeframe)
        );
        """,
    ),
    (
        3,
        "Create workspaces and chart drawings",
        """
        -- A workspace is a saved screen layout: the chart grid, each chart's
        -- symbol, timeframe, indicators and style, and the panels.
        CREATE TABLE workspaces (
            name       TEXT PRIMARY KEY,
            layout     TEXT NOT NULL,     -- JSON
            updated_at TEXT NOT NULL
        );

        -- Lines, boxes, Fibonacci levels and notes drawn on charts, kept per symbol.
        CREATE TABLE drawings (
            id         TEXT PRIMARY KEY,
            symbol     TEXT NOT NULL,
            drawing    TEXT NOT NULL,     -- JSON: kind, points, color, text
            updated_at TEXT NOT NULL
        );
        CREATE INDEX drawings_by_symbol ON drawings (symbol);
        """,
    ),
    (
        4,
        "Create accounts, trades and the risk guard log",
        """
        -- Trading accounts (paper or broker), with their risk rules as JSON.
        CREATE TABLE accounts (
            id         TEXT PRIMARY KEY,
            config     TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        -- Running state per account: trading day, drawdown high-water mark, halts.
        CREATE TABLE account_state (
            account_id TEXT PRIMARY KEY,
            state      TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        -- The paper broker's books: balance, positions and working orders per account.
        CREATE TABLE paper_books (
            account_id TEXT PRIMARY KEY,
            book       TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        -- Every fill (trade execution), on every account.
        CREATE TABLE fills (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id  TEXT NOT NULL,
            order_id    TEXT NOT NULL,
            symbol      TEXT NOT NULL,
            side        TEXT NOT NULL,
            quantity    REAL NOT NULL,
            price       REAL NOT NULL,
            fee         REAL NOT NULL,
            realized    REAL NOT NULL,   -- profit or loss this fill closed, before fees
            role        TEXT NOT NULL,   -- entry, stop_loss, take_profit, close
            source      TEXT NOT NULL,
            time        REAL NOT NULL    -- unix seconds UTC
        );
        CREATE INDEX fills_by_account ON fills (account_id, time);

        -- Every risk guard decision: what was asked, the rule that decided, the numbers, the result.
        CREATE TABLE guard_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            time       REAL NOT NULL,
            account_id TEXT,
            symbol     TEXT,
            action     TEXT NOT NULL,    -- place, cancel, modify_stop, kill_switch, ...
            approved   INTEGER NOT NULL,
            rule       TEXT NOT NULL,
            reason     TEXT NOT NULL,
            numbers    TEXT NOT NULL,    -- JSON
            source     TEXT NOT NULL
        );
        CREATE INDEX guard_log_by_time ON guard_log (time);

        -- Alerts shown to the owner (warnings, blocks, disconnects, kill switch).
        CREATE TABLE alerts (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            time     REAL NOT NULL,
            level    TEXT NOT NULL,      -- info, warning, danger
            message  TEXT NOT NULL,
            account_id TEXT
        );
        """,
    ),
    (
        5,
        "Create scripts and automation runs",
        """
        -- The owner's Python scripts: indicators, strategies and automations.
        CREATE TABLE scripts (
            id         TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            kind       TEXT NOT NULL,     -- indicator, strategy, automation, unknown
            code       TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        -- Strategies and automations set up to run, and on which account and symbol.
        CREATE TABLE runs (
            id         TEXT PRIMARY KEY,
            config     TEXT NOT NULL,     -- JSON
            updated_at TEXT NOT NULL
        );
        """,
    ),
    (
        6,
        "Create login and remote access tables",
        """
        -- The owner's login for remote access (browser or phone on another device).
        -- The password is stored only as a salted scrypt hash; the two-factor secret
        -- is what the authenticator app also knows.
        CREATE TABLE auth (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE sessions (
            token_hash TEXT PRIMARY KEY,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            client     TEXT NOT NULL
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
