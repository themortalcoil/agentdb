"""City simulation seeding: default service code and initial KV state.

Used once at startup to populate the virtual FS and KV store so the
simulation and agents have a consistent starting state.
"""

import json
import textwrap

from agentdb.db.filesystem import VirtualFS
from agentdb.db.kvstore import KVStore
from agentdb.simulation.deps import ServiceGraph


# Default Python code for each city service's main.py (handle_load contract).
SERVICE_CODE: str = textwrap.dedent("""\
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
""")


def seed_services(fs: VirtualFS, graph: ServiceGraph) -> None:
    """Write default handle_load code and config.json for each service."""
    for name in graph.services:
        capacity = graph.capacities.get(name, 1.0)
        fs.write_file(f"/city/services/{name}/main.py", SERVICE_CODE)
        fs.write_file(
            f"/city/services/{name}/config.json",
            json.dumps({"capacity": capacity}),
        )


def seed_kv_state(kv: KVStore, graph: ServiceGraph) -> None:
    """Populate initial KV entries for city state."""
    initial: dict[str, str] = {
        "city:population": "10000",
        "city:budget": "100000",
    }
    for name in graph.services:
        initial[f"service:{name}:status"] = "ok"
        initial[f"service:{name}:load"] = "0.5"
    kv.set_many(initial)
