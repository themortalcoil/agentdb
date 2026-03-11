"""Tool call audit trail backed by AgentFS tool_calls table."""

import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass
class ToolCallTracker:
    """Mutable tracker used inside the track context manager."""
    result: str | None = None
    error: str | None = None


class AuditLog:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def log(
        self,
        name: str,
        parameters: str,
        result: str | None,
        error: str | None = None,
        agent_name: str | None = None,
    ) -> int | None:
        now_ms = int(time.time() * 1000)
        cursor = self._conn.execute(
            """INSERT INTO tool_calls
               (agent_name, name, parameters, result, error, started_at, completed_at, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (agent_name, name, parameters, result, error, now_ms, now_ms, 0),
        )
        self._conn.commit()
        return cursor.lastrowid

    @contextmanager
    def track(self, name: str, parameters: str):
        tracker = ToolCallTracker()
        started = int(time.time() * 1000)
        try:
            yield tracker
        except Exception as e:
            tracker.error = str(e)
            raise
        finally:
            completed = int(time.time() * 1000)
            self._conn.execute(
                """INSERT INTO tool_calls
                   (agent_name, name, parameters, result, error, started_at, completed_at, duration_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (None, name, parameters, tracker.result, tracker.error,
                 started, completed, completed - started),
            )
            self._conn.commit()

    def query(
        self,
        name: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        sql = "SELECT * FROM tool_calls"
        params: list = []
        if name:
            sql += " WHERE name = ?"
            params.append(name)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
