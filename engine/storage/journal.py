"""The journal: the permanent record of fills, risk guard decisions and alerts.

Bible principle 5, "transparent": every decision, order and rule check is
logged and visible to the owner.
"""

import json
from pathlib import Path

from engine.storage.database import connect


class Journal:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    # ---- Fills --------------------------------------------------------------

    def record_fill(self, fill: dict) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO fills (account_id, order_id, symbol, side, quantity, price, fee, realized, role, source, time) "
                "VALUES (:account_id, :order_id, :symbol, :side, :quantity, :price, :fee, :realized, :role, :source, :time)",
                fill,
            )

    def fills(self, account_id: str | None = None, since: float = 0, limit: int = 500) -> list[dict]:
        query = "SELECT * FROM fills WHERE time >= ?"
        args: list = [since]
        if account_id:
            query += " AND account_id = ?"
            args.append(account_id)
        query += " ORDER BY time DESC, id DESC LIMIT ?"
        args.append(limit)
        with connect(self.db_path) as conn:
            return [dict(row) for row in conn.execute(query, args)]

    # ---- Risk guard log -----------------------------------------------------

    def record_decision(self, entry: dict) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO guard_log (time, account_id, symbol, action, approved, rule, reason, numbers, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    entry["time"], entry.get("account_id"), entry.get("symbol"), entry["action"],
                    1 if entry["approved"] else 0, entry["rule"], entry["reason"],
                    json.dumps(entry.get("numbers", {}), default=str), entry.get("source", ""),
                ),
            )

    def decisions(self, limit: int = 200, account_id: str | None = None) -> list[dict]:
        query = "SELECT * FROM guard_log"
        args: list = []
        if account_id:
            query += " WHERE account_id = ?"
            args.append(account_id)
        query += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with connect(self.db_path) as conn:
            rows = [dict(row) for row in conn.execute(query, args)]
        for row in rows:
            row["approved"] = bool(row["approved"])
            row["numbers"] = json.loads(row["numbers"])
        return rows

    # ---- Alerts -------------------------------------------------------------

    def record_alert(self, time: float, level: str, message: str, account_id: str | None = None) -> dict:
        with connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO alerts (time, level, message, account_id) VALUES (?, ?, ?, ?)",
                (time, level, message, account_id),
            )
            alert_id = cursor.lastrowid
        return {"id": alert_id, "time": time, "level": level, "message": message, "account_id": account_id}

    def alerts(self, limit: int = 100) -> list[dict]:
        with connect(self.db_path) as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,))]

    # ---- Key-value state (account state, paper books) -----------------------

    def load_state(self, table: str, account_id: str) -> dict | None:
        column = "state" if table == "account_state" else "book"
        with connect(self.db_path) as conn:
            row = conn.execute(f"SELECT {column} FROM {table} WHERE account_id = ?", (account_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_state(self, table: str, account_id: str, data: dict) -> None:
        column = "state" if table == "account_state" else "book"
        from engine.storage.database import utc_now
        with connect(self.db_path) as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO {table} (account_id, {column}, updated_at) VALUES (?, ?, ?)",
                (account_id, json.dumps(data), utc_now()),
            )
