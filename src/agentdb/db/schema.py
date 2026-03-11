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
    agent_name TEXT,
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
CREATE INDEX IF NOT EXISTS idx_tool_calls_agent ON tool_calls(agent_name);

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
