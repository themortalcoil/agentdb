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
