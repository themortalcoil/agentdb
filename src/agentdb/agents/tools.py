"""Agent tool functions that read/write the AgentFS city database."""

from __future__ import annotations

import json
import time
from contextlib import contextmanager

from agentdb.db.audit import AuditLog
from agentdb.db.filesystem import VirtualFS
from agentdb.db.kvstore import KVStore
from agentdb.db.overlay import OverlayFS


class CityTools:
    """Container for all agent tool functions.

    Each method becomes a LangChain tool when wrapped in the swarm module.
    All path-based operations validate that paths are under /city/.
    """

    def __init__(
        self,
        fs: VirtualFS,
        kv: KVStore,
        overlay: OverlayFS,
        event_buffer: list | None = None,
        audit: AuditLog | None = None,
    ):
        self.fs = fs
        self.kv = kv
        self.overlay = overlay
        self._incident_counter = 0
        self._events = event_buffer if event_buffer is not None else []
        self._audit = audit
        self._current_agent: str | None = None
        self._recent_audit_ids: list[int] = []

    def set_current_agent(self, name: str | None) -> None:
        """Set the agent name for attribution on subsequent tool calls."""
        self._current_agent = name

    def pop_audit_ids(self) -> list[int]:
        """Return and clear collected audit row IDs."""
        ids = self._recent_audit_ids
        self._recent_audit_ids = []
        return ids

    def _emit(self, event_type: str, **kwargs) -> None:
        """Append an event to the event buffer."""
        self._events.append({"type": event_type, "agent": self._current_agent, **kwargs})

    def _validate_path(self, path: str) -> str | None:
        """Return error string if path is invalid, None if OK."""
        if not path.startswith("/city/"):
            return f"ERROR: Path must be under /city/, got: {path}"
        return None

    @contextmanager
    def _audit_ctx(self, name: str, params: str = ""):
        if self._audit is None:
            yield
            return
        with self._audit.track(name, params, agent_name=self._current_agent) as tracker:
            yield tracker
        if tracker.row_id is not None:
            self._recent_audit_ids.append(tracker.row_id)

    # --- Mayor tools ---

    def read_city_state(self) -> str:
        """Read current city state: service statuses, agent states, priorities."""
        with self._audit_ctx("read_city_state"):
            items = self.kv.list_prefix("city:")
            items += self.kv.list_prefix("service:")
            items += self.kv.list_prefix("incident:")
            items += self.kv.list_prefix("mayor:")
            return json.dumps(dict(items), indent=2)

    def set_priority(self, priority: str) -> str:
        """Set the current city priority."""
        with self._audit_ctx("set_priority", priority):
            self.kv.set("mayor:priority", priority)
            return f"Priority set to: {priority}"

    def assign_task(self, service: str, description: str, assigned_to: str) -> str:
        """Create a task assignment for an agent."""
        with self._audit_ctx("assign_task", f"{service}:{assigned_to}"):
            task_id = f"TASK-{int(time.time()) % 100000:05d}"
            task_data = json.dumps(
                {
                    "id": task_id,
                    "service": service,
                    "description": description,
                    "assigned_to": assigned_to,
                    "status": "assigned",
                    "created_at": int(time.time()),
                }
            )
            task_path = f"/city/plans/{task_id}.json"
            self.fs.write_file(task_path, task_data)
            self._emit("fs_change", path=task_path, action="write", size=len(task_data))
            return f"Assigned {task_id} to {assigned_to}: {description}"

    # --- Engineer tools ---

    def write_file(self, path: str, content: str) -> str:
        """Write a file to the city filesystem (production)."""
        with self._audit_ctx("write_file", path):
            if err := self._validate_path(path):
                return err
            old_content = self.fs.read_file(path)
            self.fs.write_file(path, content)
            self._emit(
                "code_diff", path=path, old_content=old_content, new_content=content, action="write"
            )
            self._emit("fs_change", path=path, action="write", size=len(content))
            return f"Written {len(content)} bytes to {path}"

    def read_file(self, path: str) -> str:
        """Read a file from the city filesystem."""
        with self._audit_ctx("read_file", path):
            if err := self._validate_path(path):
                return err
            content = self.fs.read_file(path)
            if content is None:
                return f"File not found: {path}"
            return content

    def deploy_staging(self, path: str, content: str) -> str:
        """Write a file to the staging overlay."""
        with self._audit_ctx("deploy_staging", path):
            if err := self._validate_path(path):
                return err
            old_content = self.fs.read_file(path)
            self.overlay.write_file(path, content)
            self._emit(
                "code_diff", path=path, old_content=old_content, new_content=content, action="stage"
            )
            self._emit("fs_change", path=path, action="stage", size=len(content))
            return f"Staged {len(content)} bytes to {path}"

    def run_tests(self, service: str) -> str:
        """Check if staged service code compiles."""
        with self._audit_ctx("run_tests", service):
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
        with self._audit_ctx("read_metrics", service):
            status = self.kv.get(f"service:{service}:status", "unknown")
            load = self.kv.get(f"service:{service}:load", "0")
            return json.dumps({"service": service, "status": status, "load": load})

    def check_health(self) -> str:
        """Check health of all services (discovered from KV store)."""
        with self._audit_ctx("check_health"):
            service_keys = self.kv.list_prefix("service:")
            service_names = {k.split(":")[1] for k, _ in service_keys}
            health = {}
            for svc in sorted(service_names):
                health[svc] = {
                    "status": self.kv.get(f"service:{svc}:status", "unknown"),
                    "load": self.kv.get(f"service:{svc}:load", "0"),
                }
            return json.dumps(health, indent=2)

    def create_incident(self, service: str, description: str, severity: str) -> str:
        """Create an incident record."""
        with self._audit_ctx("create_incident", f"{service}:{severity}"):
            self._incident_counter += 1
            inc_id = f"INC-{self._incident_counter:03d}"
            incident = json.dumps(
                {
                    "id": inc_id,
                    "service": service,
                    "description": description,
                    "severity": severity,
                    "status": "open",
                    "created_at": int(time.time()),
                }
            )
            path = f"/city/incidents/{inc_id}.json"
            self.fs.write_file(path, incident)
            self._emit("fs_change", path=path, action="write", size=len(incident))
            raw = self.kv.get("incident:total_created", "0")
            count = int(raw or "0") + 1
            self.kv.set("incident:total_created", str(count))
            return inc_id

    # --- Fixer tools ---

    def patch_file(self, path: str, content: str) -> str:
        """Patch a file in the staging overlay."""
        with self._audit_ctx("patch_file", path):
            if err := self._validate_path(path):
                return err
            old_content = self.fs.read_file(path)
            self.overlay.write_file(path, content)
            self._emit(
                "code_diff", path=path, old_content=old_content, new_content=content, action="stage"
            )
            self._emit("fs_change", path=path, action="stage", size=len(content))
            return f"Patched {path} in staging ({len(content)} bytes)"

    def hotfix_prod(self, service: str) -> str:
        """Merge staging overlay changes into production.

        Note: merges ALL overlay changes, not just the target service.
        This is intentional -- in a real incident, the Fixer owns the
        entire staging layer. Scoped merges can be added later if needed.
        """
        with self._audit_ctx("hotfix_prod", service):
            changes = self.overlay.list_changes()
            if not changes:
                return f"No staged changes to merge (context: {service})"
            for change in changes:
                if change.change_type == "modified":
                    old_content = self.fs.read_file(change.path)
                    new_content = self.overlay.read_file(change.path)
                    self._emit(
                        "code_diff",
                        path=change.path,
                        old_content=old_content,
                        new_content=new_content,
                        action="merge",
                    )
                    self._emit(
                        "fs_change",
                        path=change.path,
                        action="merge",
                        size=len(new_content) if new_content is not None else 0,
                    )
                elif change.change_type == "deleted":
                    self._emit("fs_change", path=change.path, action="delete", size=0)
            self.overlay.merge()
            return f"Hotfix applied: {len(changes)} files merged to production (context: {service})"

    def rollback(self, service: str) -> str:
        """Discard all staging changes (rollback).

        Note: discards ALL overlay changes. The service parameter is used
        for logging context only.
        """
        with self._audit_ctx("rollback", service):
            changes = self.overlay.list_changes()
            for change in changes:
                self._emit("fs_change", path=change.path, action="delete", size=0)
            self.overlay.discard()
            return f"Rolled back all staged changes (context: {service})"
