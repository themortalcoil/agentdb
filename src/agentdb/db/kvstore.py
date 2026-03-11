"""Key-value store backed by AgentFS kv_store table."""

import sqlite3


class KVStore:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def get(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM kv_store WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set(self, key: str, value: str) -> None:
        self._conn.execute(
            """INSERT INTO kv_store (key, value)
               VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = unixepoch()""",
            (key, value),
        )
        self._conn.commit()

    def set_many(self, items: dict[str, str]) -> None:
        self._conn.executemany(
            """INSERT INTO kv_store (key, value)
               VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE
               SET value = excluded.value, updated_at = unixepoch()""",
            list(items.items()),
        )
        self._conn.commit()

    def delete(self, key: str) -> None:
        self._conn.execute("DELETE FROM kv_store WHERE key = ?", (key,))
        self._conn.commit()

    def list_prefix(self, prefix: str) -> list[tuple[str, str]]:
        rows = self._conn.execute(
            "SELECT key, value FROM kv_store WHERE key LIKE ? ORDER BY key",
            (prefix + "%",),
        ).fetchall()
        return [(row["key"], row["value"]) for row in rows]
