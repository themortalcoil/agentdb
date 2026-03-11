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
