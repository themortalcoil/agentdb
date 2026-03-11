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
        """Check health of all services (discovered from KV store)."""
        service_keys = self.kv.list_prefix("service:")
        service_names = {k.split(":")[1] for k, _ in service_keys}
        health = {}
        for svc in sorted(service_names):
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
        """Merge staging overlay changes into production.

        Note: merges ALL overlay changes, not just the target service.
        This is intentional -- in a real incident, the Fixer owns the
        entire staging layer. Scoped merges can be added later if needed.
        """
        changes = self.overlay.list_changes()
        service_changes = [c for c in changes if service in c.path]
        if not service_changes:
            return f"No staged changes for {service}"
        self.overlay.merge()
        return (
            f"Hotfix applied: {len(service_changes)} files merged to production"
        )

    def rollback(self, service: str) -> str:
        """Discard all staging changes (rollback).

        Note: discards ALL overlay changes. The service parameter is used
        for logging context only.
        """
        self.overlay.discard()
        return f"Rolled back all staged changes (context: {service})"
