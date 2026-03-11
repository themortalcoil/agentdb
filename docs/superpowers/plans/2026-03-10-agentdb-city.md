# AgentDB: "The City" Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a multi-agent city simulation where LLM agents manage infrastructure services by writing real Python code into an AgentFS SQLite database, with a live web dashboard.

**Architecture:** Four layers built bottom-up: AgentFS database, simulation engine, LangGraph agent swarm, FastAPI web dashboard. Each layer only depends on layers below it.

**Tech Stack:** Python 3.11+, LangGraph Swarm, SQLite (AgentFS schema), FastAPI + WebSocket, Ollama cloud (GLM-5 + MiniMax M2.5), vanilla JS + Canvas

**Spec:** `docs/superpowers/specs/2026-03-10-agentdb-city-design.md`

---

## File Structure

```
agentdb/
├── pyproject.toml                    # Dependencies and project config
├── justfile                          # Dev commands (test, run, lint)
├── main.py                           # Entry point — starts engine + dashboard
├── src/
│   └── agentdb/
│       ├── __init__.py
│       ├── db/
│       │   ├── __init__.py
│       │   ├── schema.py             # AgentFS table creation + DB init
│       │   ├── kvstore.py            # KV store CRUD operations
│       │   ├── audit.py              # Tool call audit trail logging
│       │   ├── filesystem.py         # Virtual filesystem read/write/delete/list
│       │   └── overlay.py            # Overlay filesystem (staging/prod branching)
│       ├── simulation/
│       │   ├── __init__.py
│       │   ├── deps.py               # Service dependency graph
│       │   ├── evaluator.py          # Service code evaluation (import + run)
│       │   ├── events.py             # Event types, generation, random events
│       │   └── engine.py             # Tick loop, city clock, demand curves
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── tools.py              # All agent tool functions
│       │   ├── definitions.py        # Agent configs (Mayor, Engineer, Monitor, Fixer)
│       │   └── swarm.py              # LangGraph swarm assembly + LLM routing
│       └── dashboard/
│           ├── __init__.py
│           ├── app.py                # FastAPI app, routes, WebSocket endpoint
│           ├── broadcast.py          # WebSocket event broadcaster + DB change hooks
│           └── static/
│               ├── index.html        # Dashboard layout (4 panels + timeline)
│               ├── style.css         # CSS Grid layout, health colors, animations
│               ├── app.js            # WebSocket client, panel updates, controls
│               └── graph.js          # Canvas city map rendering
├── tests/
│   ├── __init__.py
│   ├── conftest.py                   # Shared fixtures (in-memory DB, test filesystem)
│   ├── test_schema.py
│   ├── test_kvstore.py
│   ├── test_audit.py
│   ├── test_filesystem.py
│   ├── test_overlay.py
│   ├── test_deps.py
│   ├── test_evaluator.py
│   ├── test_events.py
│   ├── test_engine.py
│   ├── test_tools.py
│   └── test_swarm.py
```

---

## Chunk 1: Project Setup & Database Foundation

### Task 1: Project Setup

**Files:**
- Modify: `pyproject.toml`
- Modify: `justfile`
- Create: `src/agentdb/__init__.py`
- Create: `src/agentdb/db/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Update pyproject.toml with all dependencies**

```toml
[project]
name = "agentdb"
version = "0.1.0"
description = "Multi-agent city simulation with AgentFS"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "langchain>=0.3",
    "langchain-ollama>=0.3",
    "langgraph>=0.4",
    "langgraph-swarm>=0.1",
    "ollama>=0.6.1",
    "fastapi>=0.115",
    "uvicorn[standard]>=0.34",
    "websockets>=14.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.25",
    "httpx>=0.28",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/agentdb"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 2: Update justfile with dev commands**

```justfile
default:
    @just --list

install:
    uv sync --all-extras

test *args:
    uv run pytest {{args}}

run:
    uv run python main.py

lint:
    uv run ruff check src/ tests/
```

- [ ] **Step 3: Create package structure**

`src/agentdb/__init__.py`:
```python
"""AgentDB: Multi-agent city simulation with AgentFS."""
```

`src/agentdb/db/__init__.py`:
```python
"""AgentFS database layer."""
```

`tests/__init__.py`: empty file

- [ ] **Step 4: Create test fixtures**

`tests/conftest.py`:
```python
import sqlite3
import pytest
from agentdb.db.schema import init_db


@pytest.fixture
def db():
    """In-memory SQLite database with AgentFS schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()
```

- [ ] **Step 5: Install dependencies**

Run: `uv sync --all-extras`
Expected: all packages install successfully

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml justfile src/ tests/
git commit -m "feat: project setup with dependencies and test fixtures"
```

---

### Task 2: AgentFS Schema

**Files:**
- Create: `src/agentdb/db/schema.py`
- Create: `tests/test_schema.py`

- [ ] **Step 1: Write the failing test**

`tests/test_schema.py`:
```python
import sqlite3
from agentdb.db.schema import init_db, EXPECTED_TABLES


def test_init_db_creates_all_tables(db):
    cursor = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = {row["name"] for row in cursor.fetchall()}
    assert EXPECTED_TABLES.issubset(tables)


def test_init_db_is_idempotent(db):
    """Calling init_db twice should not raise."""
    init_db(db)
    cursor = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = {row["name"] for row in cursor.fetchall()}
    assert EXPECTED_TABLES.issubset(tables)


def test_wal_mode_enabled(db):
    mode = db.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_schema.py -v`
Expected: FAIL with ImportError or ModuleNotFoundError

- [ ] **Step 3: Implement schema.py**

`src/agentdb/db/schema.py`:
```python
"""AgentFS SQLite schema initialization."""

import sqlite3

EXPECTED_TABLES = {
    "tool_calls",
    "fs_config",
    "fs_inode",
    "fs_dentry",
    "fs_data",
    "fs_symlink",
    "fs_whiteout",
    "fs_origin",
    "kv_store",
}

SCHEMA_SQL = """
-- Tool call audit trail
CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    parameters TEXT,
    result TEXT,
    error TEXT,
    started_at INTEGER NOT NULL,
    completed_at INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tool_calls_name ON tool_calls(name);
CREATE INDEX IF NOT EXISTS idx_tool_calls_started_at ON tool_calls(started_at);

-- Virtual filesystem
CREATE TABLE IF NOT EXISTS fs_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fs_inode (
    ino INTEGER PRIMARY KEY AUTOINCREMENT,
    mode INTEGER NOT NULL,
    nlink INTEGER NOT NULL DEFAULT 0,
    uid INTEGER NOT NULL DEFAULT 0,
    gid INTEGER NOT NULL DEFAULT 0,
    size INTEGER NOT NULL DEFAULT 0,
    atime INTEGER NOT NULL,
    mtime INTEGER NOT NULL,
    ctime INTEGER NOT NULL,
    rdev INTEGER NOT NULL DEFAULT 0,
    atime_nsec INTEGER NOT NULL DEFAULT 0,
    mtime_nsec INTEGER NOT NULL DEFAULT 0,
    ctime_nsec INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS fs_dentry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    parent_ino INTEGER NOT NULL,
    ino INTEGER NOT NULL,
    UNIQUE(parent_ino, name)
);
CREATE INDEX IF NOT EXISTS idx_fs_dentry_parent ON fs_dentry(parent_ino, name);

CREATE TABLE IF NOT EXISTS fs_data (
    ino INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    data BLOB NOT NULL,
    PRIMARY KEY (ino, chunk_index)
);

CREATE TABLE IF NOT EXISTS fs_symlink (
    ino INTEGER PRIMARY KEY,
    target TEXT NOT NULL
);

-- Overlay filesystem
CREATE TABLE IF NOT EXISTS fs_whiteout (
    path TEXT PRIMARY KEY,
    parent_path TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fs_whiteout_parent ON fs_whiteout(parent_path);

CREATE TABLE IF NOT EXISTS fs_origin (
    delta_ino INTEGER PRIMARY KEY,
    base_ino INTEGER NOT NULL
);

-- Key-value store
CREATE TABLE IF NOT EXISTS kv_store (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    created_at INTEGER DEFAULT (unixepoch()),
    updated_at INTEGER DEFAULT (unixepoch())
);
CREATE INDEX IF NOT EXISTS idx_kv_store_created_at ON kv_store(created_at);
"""


def init_db(conn: sqlite3.Connection) -> None:
    """Initialize the AgentFS schema and enable WAL mode."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA_SQL)
    conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_schema.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/agentdb/db/schema.py tests/test_schema.py
git commit -m "feat: AgentFS schema initialization with all tables"
```

---

### Task 3: KV Store Operations

**Files:**
- Create: `src/agentdb/db/kvstore.py`
- Create: `tests/test_kvstore.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_kvstore.py`:
```python
from agentdb.db.kvstore import KVStore


def test_set_and_get(db):
    kv = KVStore(db)
    kv.set("city:population", "12500")
    assert kv.get("city:population") == "12500"


def test_get_missing_returns_none(db):
    kv = KVStore(db)
    assert kv.get("nonexistent") is None


def test_get_missing_with_default(db):
    kv = KVStore(db)
    assert kv.get("nonexistent", "fallback") == "fallback"


def test_set_overwrites(db):
    kv = KVStore(db)
    kv.set("key", "old")
    kv.set("key", "new")
    assert kv.get("key") == "new"


def test_delete(db):
    kv = KVStore(db)
    kv.set("key", "value")
    kv.delete("key")
    assert kv.get("key") is None


def test_list_by_prefix(db):
    kv = KVStore(db)
    kv.set("service:power:status", "ok")
    kv.set("service:water:status", "degraded")
    kv.set("agent:mayor:energy", "100")
    results = kv.list_prefix("service:")
    assert len(results) == 2
    assert all(k.startswith("service:") for k, _ in results)


def test_set_many(db):
    kv = KVStore(db)
    kv.set_many({"a": "1", "b": "2", "c": "3"})
    assert kv.get("a") == "1"
    assert kv.get("b") == "2"
    assert kv.get("c") == "3"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_kvstore.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement kvstore.py**

`src/agentdb/db/kvstore.py`:
```python
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
               ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = unixepoch()""",
            (key, value, value),
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_kvstore.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/agentdb/db/kvstore.py tests/test_kvstore.py
git commit -m "feat: KV store with get/set/delete/list operations"
```

---

### Task 4: Tool Call Audit Trail

**Files:**
- Create: `src/agentdb/db/audit.py`
- Create: `tests/test_audit.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_audit.py`:
```python
import time
from agentdb.db.audit import AuditLog


def test_log_and_query(db):
    audit = AuditLog(db)
    audit.log("write_file", '{"path": "/city/services/power-grid/main.py"}', '"ok"')
    results = audit.query()
    assert len(results) == 1
    assert results[0]["name"] == "write_file"


def test_log_records_timing(db):
    audit = AuditLog(db)
    audit.log("slow_tool", "{}", '"done"')
    results = audit.query()
    assert results[0]["duration_ms"] >= 0
    assert results[0]["started_at"] > 0
    assert results[0]["completed_at"] >= results[0]["started_at"]


def test_log_error(db):
    audit = AuditLog(db)
    audit.log("bad_tool", "{}", None, error="something broke")
    results = audit.query()
    assert results[0]["error"] == "something broke"
    assert results[0]["result"] is None


def test_query_by_name(db):
    audit = AuditLog(db)
    audit.log("write_file", "{}", '"ok"')
    audit.log("read_file", "{}", '"data"')
    audit.log("write_file", "{}", '"ok"')
    results = audit.query(name="write_file")
    assert len(results) == 2


def test_query_limit(db):
    audit = AuditLog(db)
    for i in range(10):
        audit.log("tool", "{}", f'"{i}"')
    results = audit.query(limit=3)
    assert len(results) == 3


def test_context_manager(db):
    audit = AuditLog(db)
    with audit.track("my_tool", '{"arg": 1}') as tracker:
        tracker.result = '"computed"'
    results = audit.query()
    assert len(results) == 1
    assert results[0]["name"] == "my_tool"
    assert results[0]["result"] == '"computed"'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_audit.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement audit.py**

`src/agentdb/db/audit.py`:
```python
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
    ) -> int:
        now_ms = int(time.time() * 1000)
        cursor = self._conn.execute(
            """INSERT INTO tool_calls
               (name, parameters, result, error, started_at, completed_at, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (name, parameters, result, error, now_ms, now_ms, 0),
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
                   (name, parameters, result, error, started_at, completed_at, duration_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (name, parameters, tracker.result, tracker.error,
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_audit.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/agentdb/db/audit.py tests/test_audit.py
git commit -m "feat: tool call audit trail with context manager tracking"
```

---

## Chunk 2: Virtual Filesystem

### Task 5: Basic Filesystem Operations

**Files:**
- Create: `src/agentdb/db/filesystem.py`
- Create: `tests/test_filesystem.py`

The AgentFS virtual filesystem uses Unix-style inodes. We build a high-level path-based API that hides inode details. Content is stored as blobs in `fs_data` chunks, with directory entries in `fs_dentry` pointing to inodes in `fs_inode`.

- [ ] **Step 1: Write the failing tests**

`tests/test_filesystem.py`:
```python
from agentdb.db.filesystem import VirtualFS


def test_write_and_read_file(db):
    fs = VirtualFS(db)
    fs.write_file("/city/services/power-grid/main.py", "print('hello')")
    content = fs.read_file("/city/services/power-grid/main.py")
    assert content == "print('hello')"


def test_read_nonexistent_returns_none(db):
    fs = VirtualFS(db)
    assert fs.read_file("/does/not/exist") is None


def test_overwrite_file(db):
    fs = VirtualFS(db)
    fs.write_file("/city/test.py", "v1")
    fs.write_file("/city/test.py", "v2")
    assert fs.read_file("/city/test.py") == "v2"


def test_delete_file(db):
    fs = VirtualFS(db)
    fs.write_file("/city/test.py", "content")
    fs.delete("/city/test.py")
    assert fs.read_file("/city/test.py") is None


def test_list_directory(db):
    fs = VirtualFS(db)
    fs.write_file("/city/services/power-grid/main.py", "code")
    fs.write_file("/city/services/power-grid/config.json", "{}")
    entries = fs.list_dir("/city/services/power-grid")
    assert set(entries) == {"main.py", "config.json"}


def test_list_root(db):
    fs = VirtualFS(db)
    fs.write_file("/city/services/power-grid/main.py", "code")
    fs.write_file("/city/plans/TASK-001.md", "plan")
    entries = fs.list_dir("/city")
    assert "services" in entries
    assert "plans" in entries


def test_list_empty_dir(db):
    fs = VirtualFS(db)
    entries = fs.list_dir("/nonexistent")
    assert entries == []


def test_exists(db):
    fs = VirtualFS(db)
    fs.write_file("/city/test.py", "content")
    assert fs.exists("/city/test.py") is True
    assert fs.exists("/city/nope.py") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_filesystem.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement filesystem.py**

`src/agentdb/db/filesystem.py`:
```python
"""High-level virtual filesystem API over AgentFS inode tables.

Provides path-based file operations (write, read, delete, list) while
managing inodes, directory entries, and data chunks internally.
"""

import sqlite3
import time

# inode mode constants
S_IFREG = 0o100644  # regular file
S_IFDIR = 0o040755  # directory


class VirtualFS:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._ensure_root()

    def _ensure_root(self) -> None:
        """Create the root inode (ino=1) if it doesn't exist."""
        row = self._conn.execute(
            "SELECT ino FROM fs_inode WHERE ino = 1"
        ).fetchone()
        if not row:
            now = int(time.time())
            self._conn.execute(
                """INSERT INTO fs_inode (ino, mode, nlink, atime, mtime, ctime)
                   VALUES (1, ?, 1, ?, ?, ?)""",
                (S_IFDIR, now, now, now),
            )
            self._conn.commit()

    def _split_path(self, path: str) -> list[str]:
        return [p for p in path.strip("/").split("/") if p]

    def _resolve_path(self, parts: list[str]) -> int | None:
        """Walk directory entries from root, return inode number or None."""
        current_ino = 1  # root
        for name in parts:
            row = self._conn.execute(
                "SELECT ino FROM fs_dentry WHERE parent_ino = ? AND name = ?",
                (current_ino, name),
            ).fetchone()
            if not row:
                return None
            current_ino = row["ino"]
        return current_ino

    def _create_inode(self, mode: int) -> int:
        now = int(time.time())
        cursor = self._conn.execute(
            """INSERT INTO fs_inode (mode, nlink, atime, mtime, ctime)
               VALUES (?, 1, ?, ?, ?)""",
            (mode, now, now, now),
        )
        return cursor.lastrowid

    def _ensure_parents(self, parts: list[str]) -> int:
        """Create all parent directories, return parent inode."""
        current_ino = 1  # root
        for name in parts:
            row = self._conn.execute(
                "SELECT ino FROM fs_dentry WHERE parent_ino = ? AND name = ?",
                (current_ino, name),
            ).fetchone()
            if row:
                current_ino = row["ino"]
            else:
                dir_ino = self._create_inode(S_IFDIR)
                self._conn.execute(
                    "INSERT INTO fs_dentry (name, parent_ino, ino) VALUES (?, ?, ?)",
                    (name, current_ino, dir_ino),
                )
                current_ino = dir_ino
        return current_ino

    def write_file(self, path: str, content: str) -> None:
        parts = self._split_path(path)
        filename = parts[-1]
        parent_parts = parts[:-1]

        parent_ino = self._ensure_parents(parent_parts)
        existing = self._conn.execute(
            "SELECT ino FROM fs_dentry WHERE parent_ino = ? AND name = ?",
            (parent_ino, filename),
        ).fetchone()

        if existing:
            ino = existing["ino"]
            self._conn.execute("DELETE FROM fs_data WHERE ino = ?", (ino,))
            now = int(time.time())
            self._conn.execute(
                "UPDATE fs_inode SET size = ?, mtime = ? WHERE ino = ?",
                (len(content.encode()), now, ino),
            )
        else:
            ino = self._create_inode(S_IFREG)
            self._conn.execute(
                "INSERT INTO fs_dentry (name, parent_ino, ino) VALUES (?, ?, ?)",
                (filename, parent_ino, ino),
            )
            self._conn.execute(
                "UPDATE fs_inode SET size = ? WHERE ino = ?",
                (len(content.encode()), ino),
            )

        self._conn.execute(
            "INSERT INTO fs_data (ino, chunk_index, data) VALUES (?, 0, ?)",
            (ino, content.encode()),
        )
        self._conn.commit()

    def read_file(self, path: str) -> str | None:
        parts = self._split_path(path)
        ino = self._resolve_path(parts)
        if ino is None:
            return None
        rows = self._conn.execute(
            "SELECT data FROM fs_data WHERE ino = ? ORDER BY chunk_index",
            (ino,),
        ).fetchall()
        if not rows:
            return None
        return b"".join(row["data"] for row in rows).decode()

    def delete(self, path: str) -> bool:
        parts = self._split_path(path)
        ino = self._resolve_path(parts)
        if ino is None:
            return False
        filename = parts[-1]
        parent_ino = self._resolve_path(parts[:-1]) if len(parts) > 1 else 1
        self._conn.execute("DELETE FROM fs_data WHERE ino = ?", (ino,))
        self._conn.execute(
            "DELETE FROM fs_dentry WHERE parent_ino = ? AND name = ?",
            (parent_ino, filename),
        )
        self._conn.execute("DELETE FROM fs_inode WHERE ino = ?", (ino,))
        self._conn.commit()
        return True

    def list_dir(self, path: str) -> list[str]:
        parts = self._split_path(path)
        ino = self._resolve_path(parts)
        if ino is None:
            return []
        rows = self._conn.execute(
            "SELECT name FROM fs_dentry WHERE parent_ino = ? ORDER BY name",
            (ino,),
        ).fetchall()
        return [row["name"] for row in rows]

    def exists(self, path: str) -> bool:
        parts = self._split_path(path)
        return self._resolve_path(parts) is not None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_filesystem.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/agentdb/db/filesystem.py tests/test_filesystem.py
git commit -m "feat: virtual filesystem with path-based file operations"
```

---

### Task 6: Overlay Filesystem (Staging/Prod)

**Files:**
- Create: `src/agentdb/db/overlay.py`
- Create: `tests/test_overlay.py`

The overlay implements copy-on-write for staging vs production. Reads check overlay first, then fall through to base. `fs_whiteout` entries mask deletions.

- [ ] **Step 1: Write the failing tests**

`tests/test_overlay.py`:
```python
from agentdb.db.filesystem import VirtualFS
from agentdb.db.overlay import OverlayFS


def test_read_through_to_base(db):
    """Overlay reads fall through to base when no overlay file exists."""
    fs = VirtualFS(db)
    fs.write_file("/city/services/power-grid/main.py", "base code")
    overlay = OverlayFS(db, fs)
    assert overlay.read_file("/city/services/power-grid/main.py") == "base code"


def test_overlay_write_shadows_base(db):
    """Writing to overlay shadows the base file."""
    fs = VirtualFS(db)
    fs.write_file("/city/services/power-grid/main.py", "base code")
    overlay = OverlayFS(db, fs)
    overlay.write_file("/city/services/power-grid/main.py", "staged code")
    assert overlay.read_file("/city/services/power-grid/main.py") == "staged code"
    assert fs.read_file("/city/services/power-grid/main.py") == "base code"


def test_overlay_delete_creates_whiteout(db):
    """Deleting in overlay masks the base file without removing it."""
    fs = VirtualFS(db)
    fs.write_file("/city/services/power-grid/main.py", "base code")
    overlay = OverlayFS(db, fs)
    overlay.delete_file("/city/services/power-grid/main.py")
    assert overlay.read_file("/city/services/power-grid/main.py") is None
    assert fs.read_file("/city/services/power-grid/main.py") == "base code"


def test_merge_overlay_to_base(db):
    """Merging applies overlay changes to the base filesystem."""
    fs = VirtualFS(db)
    fs.write_file("/city/services/power-grid/main.py", "base code")
    overlay = OverlayFS(db, fs)
    overlay.write_file("/city/services/power-grid/main.py", "staged code")
    overlay.merge()
    assert fs.read_file("/city/services/power-grid/main.py") == "staged code"


def test_merge_applies_whiteouts(db):
    """Merging deletes base files that have whiteout entries."""
    fs = VirtualFS(db)
    fs.write_file("/city/services/power-grid/old.py", "dead code")
    overlay = OverlayFS(db, fs)
    overlay.delete_file("/city/services/power-grid/old.py")
    overlay.merge()
    assert fs.read_file("/city/services/power-grid/old.py") is None


def test_discard_overlay(db):
    """Discarding overlay removes all staged changes."""
    fs = VirtualFS(db)
    fs.write_file("/city/services/power-grid/main.py", "base code")
    overlay = OverlayFS(db, fs)
    overlay.write_file("/city/services/power-grid/main.py", "staged code")
    overlay.discard()
    assert overlay.read_file("/city/services/power-grid/main.py") == "base code"


def test_list_changes(db):
    """List all files modified or deleted in the overlay."""
    fs = VirtualFS(db)
    fs.write_file("/city/services/power-grid/main.py", "base")
    fs.write_file("/city/services/power-grid/config.json", "{}")
    overlay = OverlayFS(db, fs)
    overlay.write_file("/city/services/power-grid/main.py", "new code")
    overlay.delete_file("/city/services/power-grid/config.json")
    changes = overlay.list_changes()
    assert len(changes) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_overlay.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement overlay.py**

`src/agentdb/db/overlay.py`:
```python
"""Overlay filesystem for staging/production branching.

Uses fs_whiteout for deletions and a separate prefix namespace
in the base filesystem tables for overlay data. Stores overlay files
with a '__overlay__/' path prefix in the base VirtualFS.
"""

import sqlite3
import time
from dataclasses import dataclass

from agentdb.db.filesystem import VirtualFS

OVERLAY_PREFIX = "__overlay__"


@dataclass
class OverlayChange:
    path: str
    change_type: str  # "modified" or "deleted"


class OverlayFS:
    def __init__(self, conn: sqlite3.Connection, base_fs: VirtualFS):
        self._conn = conn
        self._base = base_fs

    def _overlay_path(self, path: str) -> str:
        return f"/{OVERLAY_PREFIX}{path}"

    def read_file(self, path: str) -> str | None:
        # Check whiteout first (file deleted in overlay)
        row = self._conn.execute(
            "SELECT path FROM fs_whiteout WHERE path = ?", (path,)
        ).fetchone()
        if row:
            return None

        # Check overlay layer
        overlay_content = self._base.read_file(self._overlay_path(path))
        if overlay_content is not None:
            return overlay_content

        # Fall through to base
        return self._base.read_file(path)

    def write_file(self, path: str, content: str) -> None:
        # Remove any whiteout for this path
        self._conn.execute("DELETE FROM fs_whiteout WHERE path = ?", (path,))
        self._conn.commit()
        # Write to overlay namespace
        self._base.write_file(self._overlay_path(path), content)

    def delete_file(self, path: str) -> None:
        # Remove overlay version if it exists
        self._base.delete(self._overlay_path(path))
        # Create whiteout entry
        parts = path.rsplit("/", 1)
        parent = parts[0] if len(parts) > 1 else "/"
        now = int(time.time())
        self._conn.execute(
            """INSERT OR REPLACE INTO fs_whiteout (path, parent_path, created_at)
               VALUES (?, ?, ?)""",
            (path, parent, now),
        )
        self._conn.commit()

    def merge(self) -> None:
        """Apply all overlay changes to the base filesystem."""
        self._merge_recursive(f"/{OVERLAY_PREFIX}", "/")

        # Apply whiteout deletions
        whiteouts = self._conn.execute(
            "SELECT path FROM fs_whiteout"
        ).fetchall()
        for row in whiteouts:
            self._base.delete(row["path"])

        self.discard()

    def _merge_recursive(self, overlay_dir: str, base_dir: str) -> None:
        entries = self._base.list_dir(overlay_dir)
        for name in entries:
            overlay_path = f"{overlay_dir}/{name}"
            base_path = f"{base_dir}/{name}"
            content = self._base.read_file(overlay_path)
            if content is not None:
                self._base.write_file(base_path, content)
            else:
                self._merge_recursive(overlay_path, base_path)

    def discard(self) -> None:
        """Discard all overlay changes."""
        self._delete_overlay_recursive(f"/{OVERLAY_PREFIX}")
        self._conn.execute("DELETE FROM fs_whiteout")
        self._conn.commit()

    def _delete_overlay_recursive(self, dir_path: str) -> None:
        entries = self._base.list_dir(dir_path)
        for name in entries:
            full_path = f"{dir_path}/{name}"
            content = self._base.read_file(full_path)
            if content is not None:
                self._base.delete(full_path)
            else:
                self._delete_overlay_recursive(full_path)
                self._base.delete(full_path)
        self._base.delete(dir_path)

    def list_changes(self) -> list[OverlayChange]:
        changes: list[OverlayChange] = []
        self._collect_changes(f"/{OVERLAY_PREFIX}", "/", changes)
        whiteouts = self._conn.execute(
            "SELECT path FROM fs_whiteout"
        ).fetchall()
        for row in whiteouts:
            changes.append(OverlayChange(path=row["path"], change_type="deleted"))
        return changes

    def _collect_changes(
        self, overlay_dir: str, base_dir: str, changes: list[OverlayChange]
    ) -> None:
        entries = self._base.list_dir(overlay_dir)
        for name in entries:
            overlay_path = f"{overlay_dir}/{name}"
            base_path = f"{base_dir}/{name}"
            content = self._base.read_file(overlay_path)
            if content is not None:
                changes.append(
                    OverlayChange(path=base_path, change_type="modified")
                )
            else:
                self._collect_changes(overlay_path, base_path, changes)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_overlay.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/agentdb/db/overlay.py tests/test_overlay.py
git commit -m "feat: overlay filesystem for staging/prod branching"
```

---

## Chunk 3: Simulation Engine

### Task 7: Service Dependency Graph

**Files:**
- Create: `src/agentdb/simulation/__init__.py`
- Create: `src/agentdb/simulation/deps.py`
- Create: `tests/test_deps.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_deps.py`:
```python
from agentdb.simulation.deps import ServiceGraph


def test_default_city_services():
    g = ServiceGraph.default_city()
    assert set(g.services) == {
        "power-grid", "water-system", "traffic-control", "comms-network"
    }


def test_dependents():
    """power-grid failing should affect water-system and comms-network."""
    g = ServiceGraph.default_city()
    dependents = g.get_dependents("power-grid")
    assert "water-system" in dependents
    assert "comms-network" in dependents


def test_cascade_order():
    """Cascade from power-grid should ripple through all dependents."""
    g = ServiceGraph.default_city()
    cascade = g.get_cascade_order("power-grid")
    assert len(cascade) >= 2


def test_no_dependents():
    """traffic-control has no dependents in the default city."""
    g = ServiceGraph.default_city()
    dependents = g.get_dependents("traffic-control")
    assert dependents == []


def test_dependencies_of():
    """traffic-control depends on comms-network."""
    g = ServiceGraph.default_city()
    deps = g.get_dependencies("traffic-control")
    assert "comms-network" in deps
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_deps.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement deps.py**

`src/agentdb/simulation/__init__.py`:
```python
"""City simulation engine."""
```

`src/agentdb/simulation/deps.py`:
```python
"""Service dependency graph for the city."""

from dataclasses import dataclass, field


@dataclass
class ServiceGraph:
    """Directed graph of service dependencies.

    An edge from A -> B means A depends on B (B failing affects A).
    """

    services: list[str] = field(default_factory=list)
    edges: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def default_city(cls) -> "ServiceGraph":
        """The default city service topology from the spec.

        Edges represent "depends on":
        - water-system depends on power-grid
        - comms-network depends on power-grid
        - traffic-control depends on comms-network
        """
        services = [
            "power-grid", "water-system", "traffic-control", "comms-network"
        ]
        edges = {
            "power-grid": [],
            "water-system": ["power-grid"],
            "comms-network": ["power-grid"],
            "traffic-control": ["comms-network"],
        }
        return cls(services=services, edges=edges)

    def get_dependencies(self, service: str) -> list[str]:
        """Services that this service depends on (upstream)."""
        return list(self.edges.get(service, []))

    def get_dependents(self, service: str) -> list[str]:
        """Services that depend on this service (downstream)."""
        return [s for s, deps in self.edges.items() if service in deps]

    def get_cascade_order(self, failed_service: str) -> list[str]:
        """BFS of all services affected by a failure, in cascade order."""
        affected: list[str] = []
        queue = [failed_service]
        visited = {failed_service}
        while queue:
            current = queue.pop(0)
            dependents = self.get_dependents(current)
            for dep in dependents:
                if dep not in visited:
                    visited.add(dep)
                    affected.append(dep)
                    queue.append(dep)
        return affected
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_deps.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/agentdb/simulation/ tests/test_deps.py
git commit -m "feat: service dependency graph with cascade detection"
```

---

### Task 8: Service Evaluator

**Files:**
- Create: `src/agentdb/simulation/evaluator.py`
- Create: `tests/test_evaluator.py`

The evaluator imports service code from the virtual filesystem and calls `handle_load()` to determine service health. This is the mechanism where agent-written code has real consequences.

- [ ] **Step 1: Write the failing tests**

`tests/test_evaluator.py`:
```python
from agentdb.db.filesystem import VirtualFS
from agentdb.simulation.evaluator import ServiceEvaluator, ServiceResult

GOOD_SERVICE = '''
def handle_load(load: float, config: dict) -> dict:
    capacity = config.get("capacity", 1.0)
    if load > capacity:
        return {
            "status": "degraded",
            "capacity": capacity,
            "metrics": {"utilization": load / capacity},
        }
    return {
        "status": "ok",
        "capacity": capacity,
        "metrics": {"utilization": load / capacity},
    }
'''

BAD_SERVICE = '''
def handle_load(load: float, config: dict) -> dict:
    return 1 / 0  # ZeroDivisionError
'''

SYNTAX_ERROR_SERVICE = '''
def handle_load(load config):  # syntax error
    pass
'''


def test_evaluate_good_service(db):
    fs = VirtualFS(db)
    fs.write_file("/city/services/power-grid/main.py", GOOD_SERVICE)
    fs.write_file("/city/services/power-grid/config.json", '{"capacity": 1.0}')
    evaluator = ServiceEvaluator(fs)
    result = evaluator.evaluate("power-grid", load=0.5)
    assert result.status == "ok"
    assert result.error is None


def test_evaluate_degraded_service(db):
    fs = VirtualFS(db)
    fs.write_file("/city/services/power-grid/main.py", GOOD_SERVICE)
    fs.write_file("/city/services/power-grid/config.json", '{"capacity": 0.4}')
    evaluator = ServiceEvaluator(fs)
    result = evaluator.evaluate("power-grid", load=0.5)
    assert result.status == "degraded"


def test_evaluate_crashing_service(db):
    fs = VirtualFS(db)
    fs.write_file("/city/services/power-grid/main.py", BAD_SERVICE)
    fs.write_file("/city/services/power-grid/config.json", '{}')
    evaluator = ServiceEvaluator(fs)
    result = evaluator.evaluate("power-grid", load=0.5)
    assert result.status == "failed"
    assert "ZeroDivisionError" in result.error


def test_evaluate_syntax_error(db):
    fs = VirtualFS(db)
    fs.write_file("/city/services/power-grid/main.py", SYNTAX_ERROR_SERVICE)
    fs.write_file("/city/services/power-grid/config.json", '{}')
    evaluator = ServiceEvaluator(fs)
    result = evaluator.evaluate("power-grid", load=0.5)
    assert result.status == "failed"
    assert result.error is not None


def test_evaluate_missing_service(db):
    fs = VirtualFS(db)
    evaluator = ServiceEvaluator(fs)
    result = evaluator.evaluate("nonexistent", load=0.5)
    assert result.status == "failed"
    assert "not found" in result.error.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_evaluator.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement evaluator.py**

`src/agentdb/simulation/evaluator.py`:
```python
"""Service code evaluator -- imports and runs agent-written service code."""

import json
import types
from dataclasses import dataclass

from agentdb.db.filesystem import VirtualFS


@dataclass
class ServiceResult:
    status: str  # "ok", "degraded", "failed"
    capacity: float
    metrics: dict
    error: str | None = None

    @classmethod
    def failed(cls, error: str) -> "ServiceResult":
        return cls(status="failed", capacity=0.0, metrics={}, error=error)


class ServiceEvaluator:
    def __init__(self, fs: VirtualFS):
        self._fs = fs

    def evaluate(self, service_name: str, load: float) -> ServiceResult:
        code = self._fs.read_file(f"/city/services/{service_name}/main.py")
        if code is None:
            return ServiceResult.failed(
                f"Service '{service_name}' not found: no main.py"
            )

        config_raw = self._fs.read_file(
            f"/city/services/{service_name}/config.json"
        )
        try:
            config = json.loads(config_raw) if config_raw else {}
        except json.JSONDecodeError as e:
            return ServiceResult.failed(f"Invalid config.json: {e}")

        try:
            module = types.ModuleType(f"service_{service_name}")
            compiled = compile(code, f"{service_name}/main.py", "exec")
            exec(compiled, module.__dict__)  # noqa: S102
        except SyntaxError as e:
            return ServiceResult.failed(f"SyntaxError in main.py: {e}")
        except Exception as e:
            return ServiceResult.failed(
                f"Failed to load main.py: {type(e).__name__}: {e}"
            )

        if not hasattr(module, "handle_load"):
            return ServiceResult.failed(
                "main.py missing handle_load() function"
            )

        try:
            raw = module.handle_load(load, config)
            return ServiceResult(
                status=raw.get("status", "failed"),
                capacity=raw.get("capacity", 0.0),
                metrics=raw.get("metrics", {}),
            )
        except Exception as e:
            return ServiceResult.failed(f"{type(e).__name__}: {e}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_evaluator.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/agentdb/simulation/evaluator.py tests/test_evaluator.py
git commit -m "feat: service evaluator that runs agent-written code"
```

---

### Task 9: Event Types & Generation

**Files:**
- Create: `src/agentdb/simulation/events.py`
- Create: `tests/test_events.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_events.py`:
```python
import random
from agentdb.simulation.events import (
    CityEvent, EventType, Severity,
    generate_demand, roll_random_events,
)


def test_event_type_values():
    assert EventType.DEMAND_SPIKE.value == "demand_spike"
    assert EventType.CASCADE_FAILURE.value == "cascade_failure"


def test_severity_ordering():
    assert Severity.LOW.weight < Severity.MEDIUM.weight
    assert Severity.MEDIUM.weight < Severity.HIGH.weight
    assert Severity.HIGH.weight < Severity.CRITICAL.weight


def test_generate_demand_produces_values():
    """Demand curve should produce values between 0 and ~2.0."""
    demands = [generate_demand(tick=t, seed_offset=0) for t in range(100)]
    assert all(0 <= d <= 2.0 for d in demands)
    assert len(set(round(d, 2) for d in demands)) > 1


def test_roll_random_events_deterministic():
    rng = random.Random(42)
    events1 = roll_random_events(
        services=["power-grid", "water-system"], tick=10, rng=rng
    )
    rng2 = random.Random(42)
    events2 = roll_random_events(
        services=["power-grid", "water-system"], tick=10, rng=rng2
    )
    assert len(events1) == len(events2)
    for e1, e2 in zip(events1, events2):
        assert e1.event_type == e2.event_type
        assert e1.service == e2.service


def test_city_event_to_dict():
    event = CityEvent(
        event_type=EventType.SERVICE_FAILURE,
        service="power-grid",
        severity=Severity.HIGH,
        message="Power grid crashed",
        tick=5,
    )
    d = event.to_dict()
    assert d["event_type"] == "service_failure"
    assert d["service"] == "power-grid"
    assert d["severity"] == "high"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_events.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement events.py**

`src/agentdb/simulation/events.py`:
```python
"""City event types and generation."""

import math
import random
from dataclasses import dataclass
from enum import Enum


class EventType(Enum):
    DEMAND_SPIKE = "demand_spike"
    SERVICE_FAILURE = "service_failure"
    INFRASTRUCTURE_DECAY = "infrastructure_decay"
    CITIZEN_COMPLAINT = "citizen_complaint"
    CASCADE_FAILURE = "cascade_failure"
    BUDGET_SHORTFALL = "budget_shortfall"


class Severity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def weight(self) -> int:
        return {"low": 1, "medium": 2, "high": 3, "critical": 4}[self.value]


EVENT_PROBABILITIES: dict[EventType, float] = {
    EventType.INFRASTRUCTURE_DECAY: 0.05,
    EventType.CITIZEN_COMPLAINT: 0.03,
    EventType.BUDGET_SHORTFALL: 0.02,
}


@dataclass
class CityEvent:
    event_type: EventType
    service: str
    severity: Severity
    message: str
    tick: int

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type.value,
            "service": self.service,
            "severity": self.severity.value,
            "message": self.message,
            "tick": self.tick,
        }


def generate_demand(tick: int, seed_offset: int = 0) -> float:
    """Generate citizen demand using sine wave + noise for daily patterns."""
    base = 0.6 + 0.4 * math.sin(2 * math.pi * (tick + seed_offset) / 100)
    noise = math.sin(tick * 7.3 + seed_offset * 3.1) * 0.15
    return max(0.0, base + noise)


def roll_random_events(
    services: list[str],
    tick: int,
    rng: random.Random,
) -> list[CityEvent]:
    """Roll for random events across all services."""
    events: list[CityEvent] = []
    for service in services:
        for event_type, prob in EVENT_PROBABILITIES.items():
            if rng.random() < prob:
                severity = {
                    EventType.INFRASTRUCTURE_DECAY: Severity.LOW,
                    EventType.CITIZEN_COMPLAINT: Severity.LOW,
                    EventType.BUDGET_SHORTFALL: Severity.MEDIUM,
                }[event_type]
                events.append(
                    CityEvent(
                        event_type=event_type,
                        service=service,
                        severity=severity,
                        message=f"{event_type.value} on {service}",
                        tick=tick,
                    )
                )
    return events
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_events.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/agentdb/simulation/events.py tests/test_events.py
git commit -m "feat: city event types with demand curves and random generation"
```

---

### Task 10: Simulation Engine (Tick Loop)

**Files:**
- Create: `src/agentdb/simulation/engine.py`
- Create: `tests/test_engine.py`

The engine is async. It runs the tick loop and emits events via callbacks. It coordinates KV store updates, service evaluation, and event generation.

- [ ] **Step 1: Write the failing tests**

`tests/test_engine.py`:
```python
from agentdb.db.kvstore import KVStore
from agentdb.db.filesystem import VirtualFS
from agentdb.simulation.engine import SimulationEngine

POWER_GRID_CODE = '''
def handle_load(load: float, config: dict) -> dict:
    capacity = config.get("capacity", 1.0)
    status = "ok" if load <= capacity else "degraded"
    return {
        "status": status,
        "capacity": capacity,
        "metrics": {"utilization": load / capacity},
    }
'''


def _setup_city(db):
    """Seed the city with working services."""
    fs = VirtualFS(db)
    kv = KVStore(db)
    services = [
        "power-grid", "water-system", "traffic-control", "comms-network"
    ]
    for svc in services:
        fs.write_file(f"/city/services/{svc}/main.py", POWER_GRID_CODE)
        fs.write_file(f"/city/services/{svc}/config.json", '{"capacity": 1.0}')
        kv.set(f"service:{svc}:status", "ok")
        kv.set(f"service:{svc}:load", "0.5")
    kv.set("city:population", "10000")
    kv.set("city:budget", "100000")
    return fs, kv


def test_engine_creation(db):
    fs, kv = _setup_city(db)
    engine = SimulationEngine(db, fs, kv, seed=42)
    assert engine.tick == 0
    assert engine.paused is False


async def test_single_tick(db):
    fs, kv = _setup_city(db)
    events_received = []
    engine = SimulationEngine(db, fs, kv, seed=42)
    engine.on_event(lambda e: events_received.append(e))
    await engine.step()
    assert engine.tick == 1
    for svc in ["power-grid", "water-system", "traffic-control", "comms-network"]:
        load = kv.get(f"service:{svc}:load")
        assert load is not None


async def test_pause_resume(db):
    fs, kv = _setup_city(db)
    engine = SimulationEngine(db, fs, kv, seed=42)
    engine.pause()
    assert engine.paused is True
    await engine.step()  # no-op when paused
    assert engine.tick == 0
    engine.resume()
    await engine.step()
    assert engine.tick == 1


async def test_broken_service_generates_failure_event(db):
    fs, kv = _setup_city(db)
    fs.write_file(
        "/city/services/power-grid/main.py",
        "def handle_load(l, c): return 1/0",
    )
    events_received = []
    engine = SimulationEngine(db, fs, kv, seed=42)
    engine.on_event(lambda e: events_received.append(e))
    await engine.step()
    failure_events = [
        e for e in events_received if e.event_type.value == "service_failure"
    ]
    assert len(failure_events) >= 1
    assert any(e.service == "power-grid" for e in failure_events)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_engine.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement engine.py**

`src/agentdb/simulation/engine.py`:
```python
"""City simulation engine -- the heartbeat of the city."""

import random
from collections.abc import Callable

from agentdb.db.filesystem import VirtualFS
from agentdb.db.kvstore import KVStore
from agentdb.simulation.deps import ServiceGraph
from agentdb.simulation.evaluator import ServiceEvaluator
from agentdb.simulation.events import (
    CityEvent, EventType, Severity,
    generate_demand, roll_random_events,
)


class SimulationEngine:
    def __init__(
        self,
        conn,
        fs: VirtualFS,
        kv: KVStore,
        seed: int = 0,
        graph: ServiceGraph | None = None,
    ):
        self._conn = conn
        self._fs = fs
        self._kv = kv
        self._rng = random.Random(seed)
        self._graph = graph or ServiceGraph.default_city()
        self._evaluator = ServiceEvaluator(fs)
        self._listeners: list[Callable[[CityEvent], None]] = []
        self.tick = 0
        self.paused = False

    def on_event(self, callback: Callable[[CityEvent], None]) -> None:
        self._listeners.append(callback)

    def _emit(self, event: CityEvent) -> None:
        for listener in self._listeners:
            listener(event)

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    async def step(self) -> list[CityEvent]:
        """Run one simulation tick. Returns events generated."""
        if self.paused:
            return []

        self.tick += 1
        all_events: list[CityEvent] = []

        # 1. Update demand per service
        for i, service in enumerate(self._graph.services):
            load = generate_demand(self.tick, seed_offset=i * 17)
            self._kv.set(f"service:{service}:load", f"{load:.3f}")

        # 2. Evaluate each service's code
        failed_services: list[str] = []
        for service in self._graph.services:
            load = float(self._kv.get(f"service:{service}:load", "0.5"))
            result = self._evaluator.evaluate(service, load)
            old_status = self._kv.get(f"service:{service}:status", "ok")
            self._kv.set(f"service:{service}:status", result.status)

            if result.status == "failed" and old_status != "failed":
                event = CityEvent(
                    event_type=EventType.SERVICE_FAILURE,
                    service=service,
                    severity=Severity.HIGH,
                    message=f"{service} failed: {result.error}",
                    tick=self.tick,
                )
                all_events.append(event)
                failed_services.append(service)
            elif result.status == "degraded" and load > float(
                self._kv.get(f"service:{service}:capacity", "1.0")
            ):
                event = CityEvent(
                    event_type=EventType.DEMAND_SPIKE,
                    service=service,
                    severity=Severity.MEDIUM,
                    message=f"{service} load ({load:.2f}) exceeds capacity",
                    tick=self.tick,
                )
                all_events.append(event)

        # 3. Check for cascade failures
        for failed in failed_services:
            cascade = self._graph.get_cascade_order(failed)
            for affected in cascade:
                current = self._kv.get(f"service:{affected}:status", "ok")
                if current != "failed":
                    self._kv.set(f"service:{affected}:status", "degraded")
                    event = CityEvent(
                        event_type=EventType.CASCADE_FAILURE,
                        service=affected,
                        severity=Severity.CRITICAL,
                        message=f"{affected} affected by {failed} failure",
                        tick=self.tick,
                    )
                    all_events.append(event)

        # 4. Roll random events
        random_events = roll_random_events(
            self._graph.services, self.tick, self._rng
        )
        all_events.extend(random_events)

        # 5. Update active incident count
        failure_count = sum(
            1
            for s in self._graph.services
            if self._kv.get(f"service:{s}:status") == "failed"
        )
        self._kv.set("incident:active_count", str(failure_count))

        # 6. Emit all events
        for event in all_events:
            self._emit(event)

        return all_events
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_engine.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/agentdb/simulation/engine.py tests/test_engine.py
git commit -m "feat: simulation engine with tick loop, evaluation, and cascades"
```

---

## Chunk 4: Agent System

### Task 11: Agent Tool Functions

**Files:**
- Create: `src/agentdb/agents/__init__.py`
- Create: `src/agentdb/agents/tools.py`
- Create: `tests/test_tools.py`

Agent tools are plain functions that read/write AgentFS. Each tool validates inputs (paths must be under `/city/`).

- [ ] **Step 1: Write the failing tests**

`tests/test_tools.py`:
```python
import json
import pytest
from agentdb.db.filesystem import VirtualFS
from agentdb.db.kvstore import KVStore
from agentdb.db.overlay import OverlayFS
from agentdb.agents.tools import CityTools


@pytest.fixture
def city_tools(db):
    fs = VirtualFS(db)
    kv = KVStore(db)
    overlay = OverlayFS(db, fs)
    return CityTools(fs=fs, kv=kv, overlay=overlay)


def test_read_city_state(city_tools):
    city_tools.kv.set("city:population", "10000")
    city_tools.kv.set("service:power-grid:status", "ok")
    result = city_tools.read_city_state()
    state = json.loads(result)
    assert "city:population" in str(state)


def test_write_file_validates_path(city_tools):
    with pytest.raises(ValueError, match="under /city/"):
        city_tools.write_file("/etc/passwd", "hack")


def test_write_and_read_file(city_tools):
    city_tools.write_file("/city/services/power-grid/main.py", "print('hello')")
    content = city_tools.read_file("/city/services/power-grid/main.py")
    assert content == "print('hello')"


def test_deploy_staging(city_tools):
    city_tools.deploy_staging(
        "/city/services/power-grid/main.py", "staged code"
    )
    assert (
        city_tools.overlay.read_file("/city/services/power-grid/main.py")
        == "staged code"
    )


def test_read_metrics(city_tools):
    city_tools.kv.set("service:power-grid:status", "ok")
    city_tools.kv.set("service:power-grid:load", "0.75")
    result = city_tools.read_metrics("power-grid")
    metrics = json.loads(result)
    assert metrics["status"] == "ok"
    assert metrics["load"] == "0.75"


def test_create_incident(city_tools):
    result = city_tools.create_incident(
        service="power-grid",
        description="Power grid is failing under load",
        severity="high",
    )
    assert "INC-" in result
    content = city_tools.fs.read_file(f"/city/incidents/{result}.json")
    assert content is not None


def test_set_priority(city_tools):
    city_tools.set_priority("reliability")
    assert city_tools.kv.get("mayor:priority") == "reliability"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tools.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement tools.py**

`src/agentdb/agents/__init__.py`:
```python
"""Agent definitions and tools."""
```

`src/agentdb/agents/tools.py`:
```python
"""Agent tool functions that read/write the AgentFS city database."""

import json
import time

from agentdb.db.filesystem import VirtualFS
from agentdb.db.kvstore import KVStore
from agentdb.db.overlay import OverlayFS


class CityTools:
    """Container for all agent tool functions.

    Each method becomes a LangChain tool when wrapped in the swarm module.
    All path-based operations validate that paths are under /city/.
    """

    def __init__(self, fs: VirtualFS, kv: KVStore, overlay: OverlayFS):
        self.fs = fs
        self.kv = kv
        self.overlay = overlay
        self._incident_counter = 0

    def _validate_path(self, path: str) -> None:
        if not path.startswith("/city/"):
            raise ValueError(f"Path must be under /city/, got: {path}")

    # --- Mayor tools ---

    def read_city_state(self) -> str:
        """Read current city state: service statuses, agent states, priorities."""
        items = self.kv.list_prefix("city:")
        items += self.kv.list_prefix("service:")
        items += self.kv.list_prefix("incident:")
        items += self.kv.list_prefix("mayor:")
        return json.dumps(dict(items), indent=2)

    def set_priority(self, priority: str) -> str:
        """Set the current city priority."""
        self.kv.set("mayor:priority", priority)
        return f"Priority set to: {priority}"

    def assign_task(
        self, service: str, description: str, assigned_to: str
    ) -> str:
        """Create a task assignment for an agent."""
        task_id = f"TASK-{int(time.time()) % 100000:05d}"
        task_data = json.dumps({
            "id": task_id,
            "service": service,
            "description": description,
            "assigned_to": assigned_to,
            "status": "assigned",
            "created_at": int(time.time()),
        })
        self.fs.write_file(f"/city/plans/{task_id}.json", task_data)
        return f"Assigned {task_id} to {assigned_to}: {description}"

    # --- Engineer tools ---

    def write_file(self, path: str, content: str) -> str:
        """Write a file to the city filesystem (production)."""
        self._validate_path(path)
        self.fs.write_file(path, content)
        return f"Written {len(content)} bytes to {path}"

    def read_file(self, path: str) -> str:
        """Read a file from the city filesystem."""
        self._validate_path(path)
        content = self.fs.read_file(path)
        if content is None:
            return f"File not found: {path}"
        return content

    def deploy_staging(self, path: str, content: str) -> str:
        """Write a file to the staging overlay."""
        self._validate_path(path)
        self.overlay.write_file(path, content)
        return f"Staged {len(content)} bytes to {path}"

    def run_tests(self, service: str) -> str:
        """Check if staged service code compiles."""
        code = self.overlay.read_file(f"/city/services/{service}/main.py")
        if code is None:
            return "No staged code found for service"
        try:
            compile(code, f"{service}/main.py", "exec")
            return f"Tests passed: {service} code compiles successfully"
        except SyntaxError as e:
            return f"Tests FAILED: SyntaxError: {e}"

    # --- Monitor tools ---

    def read_metrics(self, service: str) -> str:
        """Read current metrics for a service."""
        status = self.kv.get(f"service:{service}:status", "unknown")
        load = self.kv.get(f"service:{service}:load", "0")
        return json.dumps({
            "service": service, "status": status, "load": load
        })

    def check_health(self) -> str:
        """Check health of all services."""
        services = [
            "power-grid", "water-system", "traffic-control", "comms-network"
        ]
        health = {}
        for svc in services:
            health[svc] = {
                "status": self.kv.get(f"service:{svc}:status", "unknown"),
                "load": self.kv.get(f"service:{svc}:load", "0"),
            }
        return json.dumps(health, indent=2)

    def create_incident(
        self, service: str, description: str, severity: str
    ) -> str:
        """Create an incident record."""
        self._incident_counter += 1
        inc_id = f"INC-{self._incident_counter:03d}"
        incident = json.dumps({
            "id": inc_id,
            "service": service,
            "description": description,
            "severity": severity,
            "status": "open",
            "created_at": int(time.time()),
        })
        self.fs.write_file(f"/city/incidents/{inc_id}.json", incident)
        count = int(self.kv.get("incident:active_count", "0")) + 1
        self.kv.set("incident:active_count", str(count))
        return inc_id

    # --- Fixer tools ---

    def patch_file(self, path: str, content: str) -> str:
        """Patch a file in the staging overlay."""
        self._validate_path(path)
        self.overlay.write_file(path, content)
        return f"Patched {path} in staging ({len(content)} bytes)"

    def hotfix_prod(self, service: str) -> str:
        """Merge staging overlay changes into production."""
        changes = self.overlay.list_changes()
        service_changes = [c for c in changes if service in c.path]
        if not service_changes:
            return f"No staged changes for {service}"
        self.overlay.merge()
        return (
            f"Hotfix applied: {len(service_changes)} files merged to production"
        )

    def rollback(self, service: str) -> str:
        """Discard all staging changes (rollback)."""
        self.overlay.discard()
        return f"Rolled back all staged changes for {service}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tools.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/agentdb/agents/__init__.py src/agentdb/agents/tools.py tests/test_tools.py
git commit -m "feat: agent tool functions for city filesystem and state"
```

---

### Task 12: Agent Definitions & Swarm Assembly

**Files:**
- Create: `src/agentdb/agents/definitions.py`
- Create: `src/agentdb/agents/swarm.py`
- Create: `tests/test_swarm.py`

Wires up LangGraph Swarm with Ollama cloud models. Each agent gets its system prompt, tools, and handoff targets.

- [ ] **Step 1: Write the failing tests**

`tests/test_swarm.py`:
```python
from agentdb.agents.definitions import AGENT_CONFIGS, AgentConfig


def test_agent_configs_defined():
    assert "mayor" in AGENT_CONFIGS
    assert "engineer" in AGENT_CONFIGS
    assert "monitor" in AGENT_CONFIGS
    assert "fixer" in AGENT_CONFIGS


def test_agent_config_structure():
    for name, config in AGENT_CONFIGS.items():
        assert isinstance(config, AgentConfig)
        assert config.name == name
        assert config.model in ("glm-5:cloud", "minimax-m2.5:cloud")
        assert len(config.system_prompt) > 0
        assert len(config.tool_names) > 0
        assert len(config.handoff_targets) > 0


def test_mayor_uses_glm5():
    assert AGENT_CONFIGS["mayor"].model == "glm-5:cloud"


def test_engineer_uses_minimax():
    assert AGENT_CONFIGS["engineer"].model == "minimax-m2.5:cloud"


def test_build_swarm_returns_graph(db):
    """build_swarm should return a compiled LangGraph."""
    from agentdb.db.filesystem import VirtualFS
    from agentdb.db.kvstore import KVStore
    from agentdb.db.overlay import OverlayFS
    from agentdb.agents.swarm import build_swarm

    fs = VirtualFS(db)
    kv = KVStore(db)
    overlay = OverlayFS(db, fs)
    graph = build_swarm(fs=fs, kv=kv, overlay=overlay)
    assert graph is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_swarm.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement definitions.py**

`src/agentdb/agents/definitions.py`:
```python
"""Agent configurations for the city simulation."""

from dataclasses import dataclass


@dataclass
class AgentConfig:
    name: str
    model: str
    system_prompt: str
    tool_names: list[str]
    handoff_targets: list[str]


AGENT_CONFIGS: dict[str, AgentConfig] = {
    "mayor": AgentConfig(
        name="mayor",
        model="glm-5:cloud",
        system_prompt=(
            "You are the Mayor of a simulated city. Your job is to:\n"
            "1. Monitor overall city health by reading city state\n"
            "2. Set priorities based on current conditions\n"
            "3. Assign tasks to Engineers when infrastructure needs work\n"
            "4. Escalate to Monitor when you notice service issues\n"
            "5. Make strategic decisions during cascade failures\n\n"
            "You have a limited budget. Prioritize wisely. When multiple\n"
            "services are degraded, consider the dependency graph: fixing\n"
            "upstream services first prevents cascades."
        ),
        tool_names=["read_city_state", "set_priority", "assign_task"],
        handoff_targets=["engineer", "monitor"],
    ),
    "engineer": AgentConfig(
        name="engineer",
        model="minimax-m2.5:cloud",
        system_prompt=(
            "You are a City Engineer. You write Python code for city services.\n"
            "Each service has a main.py with a handle_load(load, config) function:\n"
            "  Returns {'status': 'ok'|'degraded'|'failed', 'capacity': float, 'metrics': dict}\n\n"
            "Workflow:\n"
            "1. Read the current service code and config\n"
            "2. Write improved code to staging using deploy_staging\n"
            "3. Run tests to verify the code compiles\n"
            "4. Hand off to Mayor for review, or to Fixer if tests fail\n\n"
            "Write clean, efficient Python. Higher capacity handles more citizens."
        ),
        tool_names=["read_file", "write_file", "deploy_staging", "run_tests"],
        handoff_targets=["mayor", "fixer"],
    ),
    "monitor": AgentConfig(
        name="monitor",
        model="glm-5:cloud",
        system_prompt=(
            "You are the City Monitor. You watch service health and detect anomalies.\n\n"
            "Responsibilities:\n"
            "1. Regularly check health of all services\n"
            "2. Read detailed metrics for services showing issues\n"
            "3. Create incidents when services are degraded or failed\n"
            "4. Hand off to Fixer for service failures\n"
            "5. Escalate to Mayor for strategic decisions\n\n"
            "Be vigilant. Catch problems early. Include detail in incidents."
        ),
        tool_names=["read_metrics", "check_health", "create_incident"],
        handoff_targets=["fixer", "mayor"],
    ),
    "fixer": AgentConfig(
        name="fixer",
        model="minimax-m2.5:cloud",
        system_prompt=(
            "You are the City Fixer. You diagnose and fix broken services.\n\n"
            "Workflow:\n"
            "1. Read the failing service's code and error details\n"
            "2. Write a fix to staging using patch_file\n"
            "3. If the fix works, apply with hotfix_prod\n"
            "4. If you can't fix it, rollback and escalate to Mayor\n"
            "5. Hand off to Monitor to confirm resolution\n\n"
            "Fix the root cause, not symptoms."
        ),
        tool_names=["read_file", "patch_file", "hotfix_prod", "rollback"],
        handoff_targets=["monitor", "mayor"],
    ),
}
```

- [ ] **Step 4: Implement swarm.py**

`src/agentdb/agents/swarm.py`:
```python
"""LangGraph Swarm assembly."""

from langchain.tools import tool
from langchain_ollama import ChatOllama
from langgraph.checkpoint.memory import InMemorySaver
from langgraph_swarm import create_handoff_tool, create_swarm

from agentdb.agents.definitions import AGENT_CONFIGS
from agentdb.agents.tools import CityTools
from agentdb.db.filesystem import VirtualFS
from agentdb.db.kvstore import KVStore
from agentdb.db.overlay import OverlayFS


def _make_langchain_tools(city_tools: CityTools, tool_names: list[str]) -> list:
    """Wrap CityTools methods as LangChain tools."""
    tool_map = {
        "read_city_state": city_tools.read_city_state,
        "set_priority": city_tools.set_priority,
        "assign_task": city_tools.assign_task,
        "write_file": city_tools.write_file,
        "read_file": city_tools.read_file,
        "deploy_staging": city_tools.deploy_staging,
        "run_tests": city_tools.run_tests,
        "read_metrics": city_tools.read_metrics,
        "check_health": city_tools.check_health,
        "create_incident": city_tools.create_incident,
        "patch_file": city_tools.patch_file,
        "hotfix_prod": city_tools.hotfix_prod,
        "rollback": city_tools.rollback,
    }
    tools = []
    for name in tool_names:
        fn = tool_map[name]
        tools.append(tool(fn))
    return tools


def build_swarm(fs: VirtualFS, kv: KVStore, overlay: OverlayFS):
    """Build and compile the LangGraph Swarm with all city agents."""
    city_tools = CityTools(fs=fs, kv=kv, overlay=overlay)
    agents = []

    for config in AGENT_CONFIGS.values():
        llm = ChatOllama(model=config.model)
        handoff_tools = [
            create_handoff_tool(agent_name=target)
            for target in config.handoff_targets
        ]
        lc_tools = _make_langchain_tools(city_tools, config.tool_names)

        from langchain.agents import create_agent

        agent = create_agent(
            llm,
            tools=lc_tools + handoff_tools,
            system_prompt=config.system_prompt,
            name=config.name,
        )
        agents.append(agent)

    workflow = create_swarm(agents, default_active_agent="monitor")
    checkpointer = InMemorySaver()
    return workflow.compile(checkpointer=checkpointer)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_swarm.py -v`
Expected: 5 passed

Note: `test_build_swarm_returns_graph` may need adjustment if `langchain.agents.create_agent` API differs from what's shown in context7 docs. The key is that the graph compiles without error. No LLM is invoked.

- [ ] **Step 6: Commit**

```bash
git add src/agentdb/agents/definitions.py src/agentdb/agents/swarm.py tests/test_swarm.py
git commit -m "feat: agent definitions and LangGraph swarm assembly"
```

---

## Chunk 5: Web Dashboard

### Task 13: FastAPI Backend & WebSocket

**Files:**
- Create: `src/agentdb/dashboard/__init__.py`
- Create: `src/agentdb/dashboard/broadcast.py`
- Create: `src/agentdb/dashboard/app.py`

- [ ] **Step 1: Implement broadcast.py**

`src/agentdb/dashboard/__init__.py`:
```python
"""Web dashboard for the city simulation."""
```

`src/agentdb/dashboard/broadcast.py`:
```python
"""WebSocket event broadcaster."""

import asyncio
import json


class Broadcaster:
    """Manages WebSocket connections and broadcasts events."""

    def __init__(self):
        self._connections: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._connections.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._connections.discard(queue)

    async def broadcast(self, event_type: str, data: dict) -> None:
        message = json.dumps({"type": event_type, "data": data})
        dead: list[asyncio.Queue] = []
        for queue in self._connections:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                dead.append(queue)
        for q in dead:
            self._connections.discard(q)

    @property
    def connection_count(self) -> int:
        return len(self._connections)
```

- [ ] **Step 2: Implement app.py**

`src/agentdb/dashboard/app.py`:
```python
"""FastAPI application with WebSocket endpoint and static file serving."""

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from agentdb.dashboard.broadcast import Broadcaster

STATIC_DIR = Path(__file__).parent / "static"


def create_app(broadcaster: Broadcaster, engine=None) -> FastAPI:
    app = FastAPI(title="AgentDB City Dashboard")

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    async def index():
        return HTMLResponse((STATIC_DIR / "index.html").read_text())

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()
        queue = broadcaster.subscribe()
        try:
            async def read_client():
                try:
                    while True:
                        data = await ws.receive_text()
                        msg = json.loads(data)
                        if engine and msg.get("action") == "pause":
                            engine.pause()
                        elif engine and msg.get("action") == "resume":
                            engine.resume()
                except WebSocketDisconnect:
                    pass

            read_task = asyncio.create_task(read_client())

            while True:
                message = await queue.get()
                await ws.send_text(message)
        except WebSocketDisconnect:
            pass
        finally:
            broadcaster.unsubscribe(queue)
            read_task.cancel()

    @app.get("/api/state")
    async def get_state():
        if engine:
            from agentdb.db.kvstore import KVStore
            kv = KVStore(engine._conn)
            items = kv.list_prefix("")
            return {
                "state": dict(items),
                "tick": engine.tick,
                "paused": engine.paused,
            }
        return {"state": {}, "tick": 0, "paused": False}

    return app
```

- [ ] **Step 3: Commit**

```bash
git add src/agentdb/dashboard/__init__.py src/agentdb/dashboard/broadcast.py src/agentdb/dashboard/app.py
git commit -m "feat: FastAPI dashboard backend with WebSocket broadcasting"
```

---

### Task 14: Dashboard Frontend

**Files:**
- Create: `src/agentdb/dashboard/static/index.html`
- Create: `src/agentdb/dashboard/static/style.css`
- Create: `src/agentdb/dashboard/static/app.js`
- Create: `src/agentdb/dashboard/static/graph.js`

The frontend is vanilla JS with CSS Grid layout, Canvas for the city map, and WebSocket for real-time updates. See spec section "Web Dashboard" for the layout design.

- [ ] **Step 1: Create index.html**

See the full HTML in the spec's dashboard layout section. Key elements:
- Header with controls (pause, inject event, speed slider)
- 4-panel CSS Grid: city map (canvas), activity feed, agent status, service detail
- Footer timeline

- [ ] **Step 2: Create style.css**

Dark theme with monospace font. Color coding: green (#b5bd68) for ok, yellow (#f0c674) for degraded, red (#cc6666) for failed.

- [ ] **Step 3: Create app.js**

WebSocket client that handles message types: `tick`, `city_event`, `kv_update`, `tool_call`, `agent_update`. Controls: `togglePause()`, `injectEvent()`, `setSpeed()`.

- [ ] **Step 4: Create graph.js**

Canvas renderer for the service dependency graph. Draws 4 nodes with icons and health-colored borders. Click detection for service selection.

Note: The full frontend code is provided inline in each step. Implement as specified in the task detail, adapting the layout from the spec's dashboard wireframe.

- [ ] **Step 5: Commit**

```bash
git add src/agentdb/dashboard/static/
git commit -m "feat: dashboard frontend with city map, activity feed, and controls"
```

---

## Chunk 6: Integration & Entry Point

### Task 15: Main Entry Point

**Files:**
- Modify: `main.py`

Wires everything together: creates the DB, seeds initial city state, starts the simulation engine tick loop, and launches the FastAPI dashboard. The agent swarm is initialized but only invoked when events trigger agent responses.

- [ ] **Step 1: Implement main.py**

Key responsibilities:
- Initialize SQLite with AgentFS schema
- Create VirtualFS, KVStore, OverlayFS
- Seed city with 4 default services (working `handle_load()` code)
- Create SimulationEngine with seed=42
- Create Broadcaster and wire event forwarding
- Create FastAPI app via `create_app()`
- Run simulation loop as asyncio background task
- Start uvicorn on port 8000

The default service code template:
```python
def handle_load(load: float, config: dict) -> dict:
    capacity = config.get("capacity", 1.0)
    utilization = load / capacity if capacity > 0 else float("inf")
    if utilization > 1.2:
        status = "failed"
    elif utilization > 0.9:
        status = "degraded"
    else:
        status = "ok"
    return {
        "status": status,
        "capacity": capacity,
        "metrics": {"utilization": round(utilization, 3)},
    }
```

- [ ] **Step 2: Smoke test**

Run: `uv run python main.py`
Open: `http://localhost:8000`
Verify: Dashboard loads, tick counter increments, service nodes update colors

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: main entry point wiring DB, simulation, and dashboard"
```

---

### Task 16: End-to-End Verification

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All tests pass (approx 55+ tests across 11 test files)

- [ ] **Step 2: Manual dashboard verification**

Run: `uv run python main.py`
Verify in browser at `http://localhost:8000`:
- City map renders 4 service nodes with health colors
- Agent cards appear (Mayor, Engineer, Monitor, Fixer)
- Activity feed shows events as simulation runs
- Tick counter increments
- Pause/resume button works
- Service nodes change color based on simulation

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "chore: end-to-end verification complete"
```

---

## Implementation Notes

### LangGraph Swarm API

The swarm uses `langchain.agents.create_agent` and `langgraph_swarm.create_swarm`. If these APIs have changed, check latest docs:
- LangGraph Swarm context7 ID: `/langchain-ai/langgraph-swarm-py`
- LangGraph context7 ID: `/websites/langchain_oss_python_langgraph`

### Ollama Cloud Models

Models accessed via `ChatOllama(model="glm-5:cloud")` and `ChatOllama(model="minimax-m2.5:cloud")`. The simulation engine and dashboard work without LLM access. Only the agent swarm requires Ollama.

### Future: Turso Migration

Replace `sqlite3.connect("city.db")` with Turso's `libsql` client. The schema is identical -- AgentFS spec is designed for both local SQLite and Turso cloud.
