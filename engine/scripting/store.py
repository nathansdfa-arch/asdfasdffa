"""The owner's scripts, saved in the database. Example scripts are added on first run,
and any example that is new in an update is added the next time the app starts."""

import re
import uuid
from pathlib import Path

from engine import paths
from engine.storage.database import connect, utc_now

EXAMPLES_DIR = paths.examples_dir()


def guess_kind(code: str) -> str:
    """A quick look at which function the script defines (the sandbox does the real check)."""
    if re.search(r"^def\s+calculate\s*\(", code, re.M):
        return "indicator"
    if re.search(r"^def\s+on_bar\s*\(", code, re.M):
        return "strategy"
    if re.search(r"^def\s+run\s*\(", code, re.M):
        return "automation"
    return "unknown"


def guess_name(code: str, fallback: str) -> str:
    match = re.search(r'^name\s*=\s*["\'](.+?)["\']', code, re.M)
    return match.group(1) if match else fallback


class ScriptStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def seed_examples(self) -> None:
        """Add every example the owner hasn't got yet. Examples already there (even edited ones) are left alone."""
        with connect(self.db_path) as conn:
            existing = {row[0] for row in conn.execute("SELECT id FROM scripts")}
        for path in sorted(EXAMPLES_DIR.glob("*.py")):
            script_id = f"example_{path.stem}"
            if script_id in existing:
                continue
            code = path.read_text(encoding="utf-8")
            self.save(None, guess_name(code, path.stem), code, script_id=script_id)

    def all(self) -> list[dict]:
        with connect(self.db_path) as conn:
            return [dict(row) for row in conn.execute("SELECT id, name, kind, updated_at FROM scripts ORDER BY kind, name")]

    def get(self, script_id: str) -> dict:
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT * FROM scripts WHERE id = ?", (script_id,)).fetchone()
        if row is None:
            raise KeyError(f"There is no script '{script_id}'.")
        return dict(row)

    def save(self, existing_id: str | None, name: str, code: str, script_id: str | None = None) -> dict:
        script_id = existing_id or script_id or uuid.uuid4().hex[:10]
        name = name.strip() or guess_name(code, "Untitled script")
        with connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO scripts (id, name, kind, code, updated_at) VALUES (?, ?, ?, ?, ?)",
                (script_id, name, guess_kind(code), code, utc_now()),
            )
        return self.get(script_id)

    def delete(self, script_id: str) -> None:
        with connect(self.db_path) as conn:
            conn.execute("DELETE FROM scripts WHERE id = ?", (script_id,))
