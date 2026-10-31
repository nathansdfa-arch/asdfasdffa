from engine.storage import database


def test_new_database_gets_every_migration(tmp_path):
    db = tmp_path / "test.db"
    version = database.initialize(db)
    assert version == database.MIGRATIONS[-1][0]
    with database.connect(db) as conn:
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"settings", "schema_version"} <= tables


def test_initializing_twice_is_harmless(tmp_path):
    db = tmp_path / "test.db"
    first = database.initialize(db)
    second = database.initialize(db)
    assert first == second
    with database.connect(db) as conn:
        rows = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    assert rows == len(database.MIGRATIONS)
