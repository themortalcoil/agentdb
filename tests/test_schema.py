import sqlite3
from agentdb.db.schema import init_db, EXPECTED_TABLES


def test_init_db_creates_all_tables(db):
    cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = {row["name"] for row in cursor.fetchall()}
    assert EXPECTED_TABLES.issubset(tables)


def test_init_db_is_idempotent(db):
    """Calling init_db twice should not raise."""
    init_db(db)
    cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = {row["name"] for row in cursor.fetchall()}
    assert EXPECTED_TABLES.issubset(tables)


def test_wal_mode_enabled(db):
    # SQLite in-memory databases do not support WAL; journal_mode stays "memory".
    # For file-based databases, init_db sets WAL. We verify the PRAGMA was issued
    # without error and that the mode is one of the expected values.
    mode = db.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode in ("wal", "memory")


def test_wal_mode_set_on_file_db(tmp_path):
    """WAL mode is applied correctly on a real file-based database."""
    from agentdb.db.schema import init_db

    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    assert mode == "wal"
