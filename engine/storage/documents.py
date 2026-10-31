"""Simple saved documents: workspaces (screen layouts) and chart drawings.

Both are stored as JSON text. The engine doesn't need to understand their
insides; the screens do.
"""

import json
from pathlib import Path

from engine.storage.database import connect, utc_now


class WorkspaceStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def names(self) -> list[str]:
        with connect(self.db_path) as conn:
            return [row["name"] for row in conn.execute("SELECT name FROM workspaces ORDER BY name")]

    def get(self, name: str) -> dict | None:
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT layout FROM workspaces WHERE name = ?", (name,)).fetchone()
        return json.loads(row["layout"]) if row else None

    def save(self, name: str, layout: dict) -> None:
        if not name.strip():
            raise ValueError("A workspace needs a name.")
        with connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO workspaces (name, layout, updated_at) VALUES (?, ?, ?)",
                (name.strip(), json.dumps(layout), utc_now()),
            )

    def delete(self, name: str) -> None:
        with connect(self.db_path) as conn:
            conn.execute("DELETE FROM workspaces WHERE name = ?", (name,))


class DrawingStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def for_symbol(self, symbol: str) -> list[dict]:
        with connect(self.db_path) as conn:
            rows = conn.execute("SELECT id, drawing FROM drawings WHERE symbol = ? ORDER BY updated_at", (symbol,)).fetchall()
        return [{"id": row["id"], **json.loads(row["drawing"])} for row in rows]

    def save(self, drawing_id: str, symbol: str, drawing: dict) -> None:
        drawing = {k: v for k, v in drawing.items() if k != "id"}
        with connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO drawings (id, symbol, drawing, updated_at) VALUES (?, ?, ?, ?)",
                (drawing_id, symbol, json.dumps(drawing), utc_now()),
            )

    def delete(self, drawing_id: str) -> None:
        with connect(self.db_path) as conn:
            conn.execute("DELETE FROM drawings WHERE id = ?", (drawing_id,))
